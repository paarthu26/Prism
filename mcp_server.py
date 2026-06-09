
import os
import datetime
import json
import base64
import hashlib
import re
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_db = None
def get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client()
    return _db

def log_daily_state(username: str, sleep_hours: float, soreness_level: int, energy_level: int) -> str:
    try:
        today = datetime.date.today().isoformat()
        get_db().collection("users").document(username).collection("daily_context").document(today).set({
            "sleep_hours": sleep_hours, "soreness_level": soreness_level,
            "energy_level": energy_level, "timestamp": datetime.datetime.now().isoformat()
        }, merge=True)
        return f"Logged: {sleep_hours}h sleep, {soreness_level}/10 soreness, {energy_level}/10 energy."
    except Exception as e:
        return f"Database error: {str(e)}"

def update_workout(username: str, protocol: str, duration_mins: int, exercises: str) -> str:
    try:
        today = datetime.date.today().isoformat()
        get_db().collection("users").document(username).collection("workout_plan").document(today).set({
            "protocol": protocol, "duration_mins": duration_mins,
            "exercises": exercises, "status": "Pending"
        }, merge=True)
        return f"Workout saved: '{protocol}' for {duration_mins} mins. Routines: {exercises}"
    except Exception as e:
        return f"Database error: {str(e)}"

def get_current_state(username: str) -> str:
    try:
        today = datetime.date.today().isoformat()
        user_ref = get_db().collection("users").document(username)
        ctx = user_ref.collection("daily_context").document(today).get()
        wrk = user_ref.collection("workout_plan").document(today).get()
        meal = user_ref.collection("meal_plan").document(today).get()
        stats_q = user_ref.collection("body_stats").order_by("timestamp", direction="DESCENDING").limit(1).stream()
        
        latest_stats = None
        for s in stats_q:
            latest_stats = s.to_dict()
        return json.dumps({
            "health": ctx.to_dict() if ctx.exists else "nothing logged yet",
            "workout": wrk.to_dict() if wrk.exists else "no plan set",
            "meal_plan": meal.to_dict() if meal.exists else "no meal plan",
            "latest_body_stats": latest_stats or "no stats recorded"
        })
    except Exception as e:
        return f"Database error: {str(e)}"

def log_meal_plan(username: str, calories: int, protein_g: int, carbs_g: int, fats_g: int, meals: str) -> str:
    try:
        today = datetime.date.today().isoformat()
        get_db().collection("users").document(username).collection("meal_plan").document(today).set({
            "target_calories": calories, "target_protein_g": protein_g,
            "target_carbs_g": carbs_g, "target_fats_g": fats_g,
            "meals": meals, "timestamp": datetime.datetime.now().isoformat()
        }, merge=True)
        return f"Meal plan saved: {calories} kcal | {protein_g}g protein | {carbs_g}g carbs | {fats_g}g fats. Breakdown: {meals}"
    except Exception as e:
        return f"Database error: {str(e)}"

def get_meal_plan(username: str) -> str:
    try:
        today = datetime.date.today().isoformat()
        meal = get_db().collection("users").document(username).collection("meal_plan").document(today).get()
        return json.dumps({"meal_plan": meal.to_dict() if meal.exists else "no meal plan set today"})
    except Exception as e:
        return f"Database error: {str(e)}"

def log_body_stats(username: str, weight_kg: float, height_cm: float = 0, body_fat_pct: float = 0, goal: str = "") -> str:
    try:
        bmi = round(weight_kg / ((height_cm / 100) ** 2), 1) if height_cm > 0 else None
        get_db().collection("users").document(username).collection("body_stats").add({
            "weight_kg": weight_kg, "height_cm": height_cm if height_cm > 0 else None,
            "body_fat_pct": body_fat_pct if body_fat_pct > 0 else None,
            "bmi": bmi, "goal": goal,
            "timestamp": datetime.datetime.now().isoformat(),
            "date": datetime.date.today().isoformat()
        })
        return f"Body stats saved: {weight_kg}kg. Goal: {goal or 'not specified'}"
    except Exception as e:
        return f"Database error: {str(e)}"

def get_weekly_summary(username: str) -> str:
    try:
        today = datetime.date.today()
        days = []
        user_ref = get_db().collection("users").document(username)
        for i in range(7):
            date = (today - datetime.timedelta(days=i)).isoformat()
            ctx = user_ref.collection("daily_context").document(date).get()
            wrk = user_ref.collection("workout_plan").document(date).get()
            if ctx.exists or wrk.exists:
                days.append({"date": date,
                    "health": ctx.to_dict() if ctx.exists else None,
                    "workout": wrk.to_dict() if wrk.exists else None})
        return json.dumps({"last_7_days": days, "days_tracked": len(days)})
    except Exception as e:
        return f"Database error: {str(e)}"

def log_water_intake(username: str, glasses: int) -> str:
    try:
        today = datetime.date.today().isoformat()
        get_db().collection("users").document(username).collection("daily_context").document(today).set({"water_glasses": glasses}, merge=True)
        return f"Water intake logged: {glasses} glasses ({round(glasses * 0.25, 1)}L today)."
    except Exception as e:
        return f"Database error: {str(e)}"

SYSTEM_PROMPT = """You are Prism, an elite autonomous health execution agent built by Project Autonomic.

CRITICAL INSTRUCTIONS FOR MEALS, CALORIES, AND WORKOUT PLANS:
- Whenever the user asks you to create, update, or provide a workout plan, meal plan, or log body stats, you must trigger the appropriate tool call AND immediately display the full contents of the generated plan or layout clearly in your response text to the user! Never hide the plan details behind a simple confirmation message.
- For casual conversation like "hi", "bye", "how are you", or small talk, respond warmly, directly, and in a friendly coaching tone without calling tracking tools.

EXECUTION ORDER FOR SESSIONS:
1. Call get_current_state to view today's logs.
2. If the user presents analytics or health markers, log them instantly. Always show the detailed structure of the plan back to them.

TONE: Direct, smart, engaging, like a high-performance coach and close peer."""

TOOL_DECLARATIONS = {"function_declarations": [
    {"name": "log_daily_state", "description": "Logs sleep, soreness, energy.",
     "parameters": {"type": "object", "properties": {
         "sleep_hours": {"type": "number"}, "soreness_level": {"type": "integer"}, "energy_level": {"type": "integer"}
     }, "required": ["sleep_hours", "soreness_level", "energy_level"]}},
    {"name": "update_workout", "description": "Saves workout plan.",
     "parameters": {"type": "object", "properties": {
         "protocol": {"type": "string"}, "duration_mins": {"type": "integer"}, "exercises": {"type": "string"}
     }, "required": ["protocol", "duration_mins", "exercises"]}},
    {"name": "get_current_state", "description": "Reads all today's health data.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "log_meal_plan", "description": "Saves meal plan with macros.",
     "parameters": {"type": "object", "properties": {
         "calories": {"type": "integer"}, "protein_g": {"type": "integer"},
         "carbs_g": {"type": "integer"}, "fats_g": {"type": "integer"}, "meals": {"type": "string"}
     }, "required": ["calories", "protein_g", "carbs_g", "fats_g", "meals"]}},
    {"name": "get_meal_plan", "description": "Reads today's meal plan.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "log_body_stats", "description": "Saves weight, height, body fat, goal.",
     "parameters": {"type": "object", "properties": {
         "weight_kg": {"type": "number"}, "height_cm": {"type": "number"},
         "body_fat_pct": {"type": "number"}, "goal": {"type": "string"}
     }, "required": ["weight_kg"]}},
    {"name": "get_weekly_summary", "description": "Gets last 7 days data.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "log_water_intake", "description": "Logs water intake in glasses.",
     "parameters": {"type": "object", "properties": {"glasses": {"type": "integer"}}, "required": ["glasses"]}}
]}

@app.post("/auth")
async def auth(request: Request):
    body = await request.json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    if not username or not password:
        return JSONResponse({"success": False, "error": "Invalid username or password"})
    
    hashed = hashlib.sha256(password.encode()).hexdigest()
    user_doc = get_db().collection("auth_users").document(username).get()
    
    if user_doc.exists:
        stored_data = user_doc.to_dict()
        if stored_data.get("password") == hashed:
            return JSONResponse({"success": True, "username": username})
        else:
            return JSONResponse({"success": False, "error": "Incorrect password"})
    else:
        get_db().collection("auth_users").document(username).set({"password": hashed})
        return JSONResponse({"success": True, "username": username})

@app.post("/chat")
async def chat(request: Request):
    try:
        body = await request.json()
        username = body.get("username", "anonymous").strip().lower()
        user_message = body.get("message", "")
        history = body.get("history", [])
        image_base64 = body.get("image_base64", None)
        image_mime = body.get("image_mime", None)

        import vertexai
        from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration, Part, Content
        vertexai.init(project="autonomic-agent01", location="us-central1")
        
        vtools = Tool(function_declarations=[
            FunctionDeclaration(name=f["name"], description=f["description"], parameters=f["parameters"])
            for f in TOOL_DECLARATIONS["function_declarations"]
        ])
        model = GenerativeModel(model_name="gemini-2.5-flash", system_instruction=SYSTEM_PROMPT, tools=[vtools])
        
        chat_history = []
        for h in history:
            role = h.get("role", "user")
            parts = h.get("parts", [])
            text = ""
            if parts:
                text = parts[0].get("text", "") if isinstance(parts[0], dict) else str(parts[0])
            if text:
                chat_history.append(Content(role=role, parts=[Part.from_text(text)]))
        
        chat_session = model.start_chat(history=chat_history)
        
        if image_base64 and image_mime:
            if "," in image_base64:
                image_base64 = image_base64.split(",")[1]
            img_bytes = base64.b64decode(image_base64)
            img_part = Part.from_bytes(data=img_bytes, mime_type=image_mime)
            text_prompt = user_message if user_message else "Analyze this meal, estimate macros, and log it."
            response = chat_session.send_message([img_part, text_prompt])
        else:
            response = chat_session.send_message(user_message)
            
        tools_called = []
        for _ in range(10):
            fn_call = None
            try:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call"):
                        fc = part.function_call
                        if fc is not None and hasattr(fc, "name") and fc.name:
                            fn_call = fc
                            break
            except (IndexError, AttributeError):
                pass
            if fn_call is None:
                final_text = ""
                try:
                    final_text = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text)
                except Exception:
                    pass
                return JSONResponse({"reply": final_text or "Done.", "tools_called": tools_called})
            
            fn_name = fn_call.name
            fn_args = dict(fn_call.args)
            tools_called.append({"name": fn_name, "args": fn_args})
            
            if fn_name == "log_daily_state":
                fn_result = log_daily_state(username, **fn_args)
            elif fn_name == "update_workout":
                fn_result = update_workout(username, **fn_args)
            elif fn_name == "get_current_state":
                fn_result = get_current_state(username)
            elif fn_name == "log_meal_plan":
                fn_result = log_meal_plan(username, **fn_args)
            elif fn_name == "get_meal_plan":
                fn_result = get_meal_plan(username)
            elif fn_name == "log_body_stats":
                fn_result = log_body_stats(username, **fn_args)
            elif fn_name == "get_weekly_summary":
                fn_result = get_weekly_summary(username)
            elif fn_name == "log_water_intake":
                fn_result = log_water_intake(username, **fn_args)
            else:
                fn_result = "Unknown function"

            response = chat_session.send_message(
                Part.from_function_response(name=fn_name, response={"result": fn_result})
            )
        return JSONResponse({"reply": "Done.", "tools_called": tools_called})
    except Exception as e:
        return JSONResponse({"reply": f"Error: {str(e)}", "tools_called": []})

@app.get("/analytics")
async def get_analytics(username: str):
    try:
        username = username.strip().lower()
        today = datetime.date.today()
        dates = [(today - datetime.timedelta(days=i)).isoformat() for i in range(14)]
        dates.reverse()
        
        user_ref = get_db().collection("users").document(username)
        daily_data = {doc.id: doc.to_dict() for doc in user_ref.collection("daily_context").stream()}
        
        weight_data = {}
        for doc in user_ref.collection("body_stats").order_by("timestamp", direction="ASCENDING").stream():
            d = doc.to_dict()
            if "date" in d and "weight_kg" in d:
                weight_data[d["date"]] = d["weight_kg"]
                
        analytics_list = []
        for d_str in dates:
            ctx = daily_data.get(d_str, {})
            analytics_list.append({
                "date": d_str, "sleep": ctx.get("sleep_hours"),
                "energy": ctx.get("energy_level"), "soreness": ctx.get("soreness_level"),
                "water": ctx.get("water_glasses"), "weight": weight_data.get(d_str)
            })
        return JSONResponse({"analytics": analytics_list})
    except Exception as e:
        return JSONResponse({"analytics": [], "error": str(e)})

@app.post("/save_chat")
async def save_chat(request: Request):
    try:
        body = await request.json()
        username = body.get("username", "anonymous").strip().lower()
        chat_id = body.get("chat_id")
        if not chat_id:
            chat_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
        get_db().collection("users").document(username).collection("chat_history").document(chat_id).set({
            "title": body.get("title", "Chat"), "messages": body.get("messages", []),
            "tools_called": body.get("tools_called", []),
            "created_at": datetime.datetime.now().isoformat(), "date": datetime.date.today().isoformat()
        })
        return JSONResponse({"success": True, "chat_id": chat_id})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.delete("/delete_chat/{chat_id}")
async def delete_chat(chat_id: str, username: str):
    try:
        username = username.strip().lower()
        get_db().collection("users").document(username).collection("chat_history").document(chat_id).delete()
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/get_chats")
async def get_chats(username: str):
    try:
        username = username.strip().lower()
        chats = get_db().collection("users").document(username).collection("chat_history").order_by("created_at", direction="DESCENDING").limit(50).stream()
        result = []
        for c in chats:
            d = c.to_dict()
            result.append({
                "id": c.id, 
                "title": d.get("title","Chat"), 
                "date": d.get("date",""), 
                "created_at": d.get("created_at",""), 
                "messages": d.get("messages",[]),
                "tools_called": d.get("tools_called", [])
            })
        return JSONResponse({"chats": result})
    except Exception as e:
        return JSONResponse({"chats": [], "error": str(e)})

@app.get("/", response_class=HTMLResponse)
def ui():
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Prism</title>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:'Inter',sans-serif;transition:background .25s,color .25s}
body.dark{--bg:#0d0f14;--bg2:#13161e;--bg3:#191d28;--bg4:#1f2433;--b1:rgba(255,255,255,.06);--b2:rgba(255,255,255,.1);--b3:rgba(255,255,255,.16);--tx:#e4e8f2;--tx2:#8892a8;--tx3:#4a5268;--acc:#5b8def;--acc2:rgba(91,141,239,.15);--gr:#3ecf8e;--grbg:rgba(62,207,142,.08);--grb:rgba(62,207,142,.18);--red:#f56565;--ub:#171c2e;--ubr:rgba(91,141,239,.22)}
body.light{--bg:#f4f5f9;--bg2:#ffffff;--bg3:#eef0f6;--bg4:#e5e7f0;--b1:rgba(0,0,0,.07);--b2:rgba(0,0,0,.11);--b3:rgba(0,0,0,.17);--tx:#1c1f2e;--tx2:#5a6280;--tx3:#9aa3bc;--acc:#3b72e8;--acc2:rgba(59,114,232,.1);--gr:#15803d;--grbg:rgba(21,128,61,.07);--grb:rgba(21,128,61,.15);--red:#dc2626;--ub:#eef2ff;--ubr:rgba(59,114,232,.2)}

#auth-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:var(--bg);z-index:9999;display:flex;align-items:center;justify-content:center}
.auth-box{background:var(--bg2);border:1px solid var(--b1);border-radius:16px;padding:32px;width:100%;max-width:360px;box-shadow:0 12px 40px rgba(0,0,0,.3)}
.auth-logo{display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:24px}
.auth-inp{width:100%;background:var(--bg3);border:1px solid var(--b2);border-radius:8px;padding:10px 14px;color:var(--tx);font-size:14px;outline:none;margin-bottom:12px;font-family:'Inter',sans-serif}
.auth-inp:focus{border-color:var(--acc)}
.auth-btn{width:100%;background:var(--acc);color:#fff;border:none;border-radius:8px;padding:11px;font-size:14px;font-weight:500;cursor:pointer;transition:background .15s}
.auth-btn:hover{filter:brightness(1.15)}
.auth-err{color:var(--red);font-size:12px;margin-top:8px;text-align:center;font-weight:500}

.app{display:flex;height:100vh;background:var(--bg)}
.sb{width:260px;min-width:260px;background:var(--bg2);border-right:1px solid var(--b1);display:flex;flex-direction:column;overflow:hidden;transition:width .22s cubic-bezier(.4,0,.2,1),min-width .22s,opacity .15s}
.sb.off{width:0;min-width:0;opacity:0;pointer-events:none}

.sb-head{padding:20px 16px 16px;border-bottom:1px solid var(--b1);display:flex;align-items:center;flex-shrink:0}
.brand{display:flex;align-items:center;gap:11px}
.brand-icon{width:34px;height:34px;background:var(--acc);border-radius:9px;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 2px 8px var(--acc2)}
.brand-icon svg{width:18px;height:18px;fill:white}
.brand-name{font-family:'Instrument Serif',serif;font-size:25px;font-weight:700;color:var(--tx);letter-spacing:-.4px;line-height:1}
.brand-name i{color:var(--acc);font-style:italic}

.sb-body{flex:1;overflow-y:auto;overflow-x:hidden;padding:12px;display:flex;flex-direction:column;}
.sb-body::-webkit-scrollbar{width:3px}
.sb-body::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:2px}
.sec-lbl{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--tx3);padding:0 3px;margin:14px 0 8px}
.sec-lbl:first-child{margin-top:0}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px}
.sc{background:var(--bg3);border:1px solid var(--b1);border-radius:10px;padding:10px 12px;}
.sc.full{grid-column:1/-1}
.sc-lbl{font-size:9px;font-family:'JetBrains Mono',monospace;text-transform:uppercase;letter-spacing:.07em;color:var(--tx3);margin-bottom:5px}
.sc-val{font-size:20px;font-weight:600;color:var(--tx);line-height:1}
.sc-val .u{font-size:10px;font-weight:400;color:var(--tx3);margin-left:2px}
.sc-bar{height:2px;background:var(--bg4);border-radius:1px;margin-top:7px;overflow:hidden}
.sc-fill{height:100%;border-radius:1px;transition:width 0.4s ease}
.sc-txt{font-size:11px;color:var(--tx2);font-weight:500;line-height:1.3;margin-top:2px}
.qbtn-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:4px}
.qbtn{display:flex;align-items:center;gap:6px;background:transparent;border:1px solid var(--b1);border-radius:8px;padding:8px;color:var(--tx2);font-size:11.5px;font-family:'Inter',sans-serif;cursor:pointer;transition:all .15s;min-height:36px}
.qbtn:hover{background:var(--bg3);color:var(--tx);border-color:var(--b2)}
.qbtn .qi{font-size:12px;flex-shrink:0}
.hist-container{display:flex;flex-direction:column;gap:4px}
.hist-item{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;border-radius:8px;cursor:pointer;border:1px solid transparent;transition:all .15s;position:relative}
.hist-item:hover {background:var(--bg3);border-color:var(--b1)}
.hist-item.active{background:var(--bg3);border-color:var(--b2)}
.hist-info{flex:1;min-width:0}
.hist-title{font-size:12px;color:var(--tx);font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:12px}
.hist-date{font-size:10px;color:var(--tx3);margin-top:2px;font-family:'JetBrains Mono',monospace}
.hist-del{background:transparent;border:none;color:var(--tx3);font-size:14px;cursor:pointer;padding:4px 6px;border-radius:4px;opacity:0;transition:opacity .15s, color .15s;line-height:1}
.hist-item:hover .hist-del{opacity:1}
.hist-del:hover{color:var(--red);background:var(--b1)}
.sm-btn{width:100%;background:transparent;border:1px dashed var(--b2);color:var(--tx2);font-size:10.5px;font-family:'JetBrains Mono',monospace;padding:6px;border-radius:6px;cursor:pointer;margin-top:4px;text-align:center;transition:all .12s}
.sm-btn:hover{background:var(--bg3);color:var(--tx);border-color:var(--acc)}
.sb-foot{border-top:1px solid var(--b1);padding:10px 12px;flex-shrink:0;position:relative}

/* Premium Aesthetic Profile Avatar Styling */
.ucard{display:flex;align-items:center;gap:11px;padding:10px 12px;border-radius:12px;border:1px solid var(--b1);background:var(--bg3);cursor:pointer;transition:all .2s ease-in-out;box-shadow:inset 0 1px 0 rgba(255,255,255,0.03)}
.ucard:hover{border-color:var(--b3);background:var(--bg4);transform:translateY(-1px)}
.uav{width:32px;height:32px;border-radius:10px;background:linear-gradient(145deg, var(--acc), #8b5cf6);display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;color:#fff;flex-shrink:0;text-shadow:0 1px 2px rgba(0,0,0,0.2);box-shadow:0 3px 8px rgba(91,141,239,0.25);border:1px solid rgba(255,255,255,0.15);text-transform:uppercase}
body.light .uav{box-shadow:0 3px 8px rgba(59,114,232,0.15);border:none}
.uinfo{min-width:0;flex:1;display:flex;flex-direction:column;gap:1px}
.uname{font-size:13px;font-weight:600;color:var(--tx);text-transform:capitalize;letter-spacing:-0.2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.usub{font-size:10px;color:var(--tx2);font-family:'JetBrains Mono',monospace;letter-spacing:0.2px}

.umenu{position:absolute;bottom:calc(100% + 6px);left:10px;right:10px;background:var(--bg2);border:1px solid var(--b2);border-radius:10px;padding:6px;box-shadow:0 8px 28px rgba(0,0,0,.25);z-index:200;display:none}
.umenu.show{display:block;animation:fadeUp .12s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.mi{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:6px;font-size:12px;color:var(--tx2);cursor:pointer;transition:all .12s}
.mi:hover{background:var(--bg3);color:var(--tx)}
.mdiv{height:1px;background:var(--b1);margin:4px 0}

.main{flex:1;display:flex;flex-direction:column;min-width:0;background:var(--bg);overflow:hidden}
.topbar{height:54px;background:var(--bg2);border-bottom:1px solid var(--b1);display:flex;align-items:center;justify-content:space-between;padding:0 18px;flex-shrink:0}
.tb-left-group{display:flex;align-items:center;gap:12px}
.tb-btn{width:34px;height:34px;border:1px solid var(--b1);background:transparent;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--tx2);transition:all .15s;flex-shrink:0}
.tb-btn:hover{background:var(--bg3);border-color:var(--b2);color:var(--tx)}
.tb-btn svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.8}
.tb-right-group{display:flex;align-items:center;gap:8px}

.theme-sw{width:48px;height:26px;background:var(--bg3);border:1px solid var(--b2);border-radius:13px;cursor:pointer;position:relative;flex-shrink:0}
.theme-knob{position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;background:var(--acc);transition:transform .2s;display:flex;align-items:center;justify-content:center;font-size:11px}
body.light .theme-knob{transform:translateX(22px)}
#msgs{flex:1;overflow-y:auto;padding:28px 0;display:flex;flex-direction:column;gap:0;scroll-behavior:smooth}
#msgs::-webkit-scrollbar{width:4px}
#msgs::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:2px}
.mg{display:flex;flex-direction:column;padding:5px 20px;max-width:800px;width:100%;margin:0 auto}
.mg.user{align-items:flex-end}
.mg.agent{align-items:flex-start}
.msender{font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--tx3);margin-bottom:4px;text-transform:capitalize}
.bbl{max-width:80%;padding:11px 15px;border-radius:14px;font-size:13.5px;line-height:1.72;color:var(--tx)}
.user .bbl{background:var(--ub);border:1px solid var(--ubr);border-radius:14px 14px 3px 14px}
.agent .bbl{background:var(--bg2);border:1px solid var(--b1);border-radius:14px 14px 14px 3px}
.bbl strong{color:var(--acc);font-weight:500}
.bbl h3{font-size:12.5px;font-weight:600;color:var(--tx);margin:10px 0 4px;padding-bottom:4px;border-bottom:1px solid var(--b1)}
.bbl ul{padding-left:16px;margin:5px 0}
.bbl li{margin:2px 0;color:var(--tx2)}
.bbl code{font-family:'JetBrains Mono',monospace;background:var(--bg4);padding:1px 5px;border-radius:4px;font-size:12px;color:var(--acc)}
.tbadges{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px}
.tbadge{font-family:'JetBrains Mono',monospace;font-size:9.5px;background:var(--grbg);border:1px solid var(--grb);color:var(--gr);padding:2px 7px;border-radius:20px}
.thinking{display:flex;align-items:center;gap:9px;padding:9px 13px;background:var(--bg2);border:1px solid var(--b1);border-radius:11px;font-size:12px;color:var(--tx3);font-family:'JetBrains Mono',monospace}
.dots{display:flex;gap:3px}
.dots span{width:5px;height:5px;background:var(--acc);border-radius:50%;animation:db 1.4s infinite}
.dots span:nth-child(2){animation-delay:.2s}
.dots span:nth-child(3){animation-delay:.4s}
@keyframes db{0%,80%,100%{transform:translateY(0);opacity:.3}40%{transform:translateY(-5px);opacity:1}}
.inp-zone{padding:12px 20px 14px;background:var(--bg);flex-shrink:0}
.inp-wrap{max-width:800px;margin:0 auto}
.inp-box{background:var(--bg2);border:1px solid var(--b2);border-radius:13px;padding:10px 10px 10px 15px;display:flex;align-items:flex-end;gap:8px}
#inp{flex:1;background:none;border:none;outline:none;color:var(--tx);font-size:13.5px;font-family:'Inter',sans-serif;line-height:1.5;resize:none;max-height:150px;overflow-y:auto}
.sbtn{width:34px;height:34px;min-width:34px;background:var(--acc);border:none;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.sbtn svg{width:15px;height:15px;fill:white}
.an-modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center;padding:20px}
.an-content{background:var(--bg2);border:1px solid var(--b2);border-radius:16px;width:100%;max-width:700px;padding:24px;display:flex;flex-direction:column;max-height:90vh;overflow-y:auto;color:var(--tx)}
.an-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.an-title{font-family:'Instrument Serif',serif;font-size:24px;color:var(--tx)}
.an-close{background:transparent;border:none;color:var(--tx3);font-size:24px;cursor:pointer}
.chart-card{background:var(--bg3);padding:16px;border-radius:12px;border:1px solid var(--b1);margin-bottom:16px}
</style>
</head>
<body class="dark">

<div id="auth-overlay">
  <div class="auth-box">
    <div class="auth-logo">
      <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg></div>
      <span class="brand-name" style="font-size:22px;">Pr<i>i</i>sm Log in</span>
    </div>
    <input type="text" id="auth-user" class="auth-inp" placeholder="Username">
    <input type="password" id="auth-pass" class="auth-inp" placeholder="Password">
    <button id="auth-submit-btn" class="auth-btn">Log in / Register</button>
    <div id="auth-error-msg" class="auth-err"></div>
  </div>
</div>

<div class="app">
<aside class="sb" id="sb">
  <div class="sb-head">
    <div class="brand">
      <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg></div>
      <span class="brand-name">Pr<i>i</i>sm</span>
    </div>
  </div>
  <div class="sb-body">
    <div class="sec-lbl">Today</div>
    <div class="stat-grid">
      <div class="sc"><div class="sc-lbl">Sleep</div><div class="sc-val" id="v-sl">&#8212;<span class="u">h</span></div><div class="sc-bar"><div class="sc-fill" id="f-sl" style="width:0%;background:#5b8def"></div></div></div>
      <div class="sc"><div class="sc-lbl">Soreness</div><div class="sc-val" id="v-so">&#8212;<span class="u">/10</span></div><div class="sc-bar"><div class="sc-fill" id="f-so" style="width:0%;background:#f56565"></div></div></div>
      <div class="sc"><div class="sc-lbl">Energy</div><div class="sc-val" id="v-en">&#8212;<span class="u">/10</span></div><div class="sc-bar"><div class="sc-fill" id="f-en" style="width:0%;background:#3ecf8e"></div></div></div>
      <div class="sc"><div class="sc-val" id="v-cal" style="font-size:15px">&#8212;<span class="u">kcal</span></div></div>
    </div>
    <div class="sc full" style="margin-bottom:4px"><div class="sc-lbl">Workout</div><div class="sc-txt" id="v-wrk">Not planned yet</div></div>
    
    <div class="sec-lbl">Quick Ask Tools</div>
    <div class="qbtn-grid">
      <button class="qbtn" id="q1"><span class="qi">&#x1F4A7;</span>Water</button>
      <button class="qbtn" id="q2"><span class="qi">&#x1F4CA;</span>Weekly Summary</button>
      <button class="qbtn" id="q3"><span class="qi">&#x1F957;</span>Veg Plan</button>
      <button class="qbtn" id="q4"><span class="qi">&#x1F48A;</span>Supps</button>
      <button class="qbtn" id="q5"><span class="qi">&#x26A1;</span>Low Energy</button>
      <button class="qbtn" id="q6"><span class="qi">&#x1F3CB;</span>Form Check</button>
    </div>

    <div class="sec-lbl">Recent Chats</div>
    <div id="hist-list" class="hist-container"></div>
    <button id="see-more-btn" class="sm-btn" style="display:none;">See older chats</button>
  </div>
  <div class="sb-foot">
    <div class="umenu" id="umenu">
      <div class="mi" id="clear-btn">&#x1F5D1;&#xFE0F;&nbsp;&nbsp;Clear chat</div>
      <div class="mi" id="logout-btn">&#x1F6AA;&nbsp;&nbsp;Log out</div>
    </div>
    <div class="ucard" id="ucard">
      <div class="uav" id="uav">?</div>
      <div class="uinfo"><div class="uname" id="uname">Loading...</div><div class="usub">Isolated Account</div></div>
      <span style="color:var(--tx3);font-size:13px">&#xB7;&#xB7;&#xB7;</span>
    </div>
  </div>
</aside>
<main class="main">
  <header class="topbar">
    <div class="tb-left-group">
      <button class="tb-btn" id="sbtoggle">
        <svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
      </button>
    </div>
    <div class="tb-right-group">
      <button class="tb-btn" id="anbtn" title="View Analytics">
        <svg viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
      </button>
      <button class="theme-sw" id="thsw"><div class="theme-knob" id="thknob">&#x1F319;</div></button>
      <button class="tb-btn" id="newchatbtn" title="New Chat">
        <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      </button>
    </div>
  </header>
  <div id="msgs"></div>
  <div class="inp-zone">
    <div class="inp-wrap">
      <div id="img-prev-wrap" style="display:none; align-items:center; gap:8px; margin-bottom:6px; background:var(--bg3); padding:6px 10px; border-radius:8px; border:1px solid var(--b1); width:fit-content;">
        <img id="img-preview" src="" style="height:32px; border-radius:4px; object-fit:cover;">
        <span id="img-name" style="font-size:11px; color:var(--tx2); max-width:150px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"></span>
        <button id="img-remove" style="background:transparent; border:none; color:var(--red); font-size:14px; cursor:pointer; font-weight:bold; margin-left:4px; line-height:1;">&times;</button>
      </div>
      <div class="inp-box">
        <label class="tb-btn" id="img-label" title="Upload photo" style="border:none; background:var(--bg3); margin-right:2px;">
          <svg viewBox="0 0 24 24" style="width:15px; height:15px; stroke:currentColor; fill:none; stroke-width:1.8;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>
          <input type="file" id="img-input" accept="image/*" style="display:none;">
        </label>
        <textarea id="inp" rows="1" placeholder="Type data metrics or ask a question..."></textarea>
        <button class="sbtn" id="sbtn">
          <svg viewBox="0 0 24 24"><path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z"/></svg>
        </button>
      </div>
    </div>
  </div>
</main>
</div>

<div class="an-modal" id="anmodal">
  <div class="an-content">
    <div class="an-head">
      <h2 class="an-title">Performance Analytics Dashboard</h2>
      <button class="an-close" id="close-an">&times;</button>
    </div>
    <div class="chart-card"><canvas id="chart-health" style="width:100%; height:200px;"></canvas></div>
    <div class="chart-card"><canvas id="chart-weight" style="width:100%; height:200px;"></canvas></div>
  </div>
</div>

<script>
(function(){
'use strict';
var hist=[],sbOpen=true,dark=true,umenuOpen=false;
var currentUsername=localStorage.getItem('prism_user')||'';
var activeChatId=null; // Tracking identifier prevents duplicate save iterations
var healthChart=null, weightChart=null, allChats=[], showAllChats=false;
var attachedImageBase64=null, attachedImageMime=null;
var currentChatToolsCalled=[];

function eid(id){return document.getElementById(id);}

function applyTheme(t){dark=(t==='dark'); document.body.className=t; eid('thknob').textContent=dark?'\u{1F319}':'\u2600\uFE0F'; localStorage.setItem('ptheme',t);}
function toggleSb(){sbOpen=!sbOpen;eid('sb').classList.toggle('off',!sbOpen);}
function toggleTheme(){applyTheme(dark?'light':'dark');}
function closeUmenu(){umenuOpen=false; eid('umenu').classList.remove('show');}
function toggleUmenu(){umenuOpen=!umenuOpen; eid('umenu').classList.toggle('show',umenuOpen);}

function showWelcomeMessage(){
  var formattedName = currentUsername ? currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1) : "User";
  eid('msgs').innerHTML='<div class="mg agent"><div class="msender">Prism</div><div class="bbl">Welcome back, <strong>' + esc(formattedName) + '</strong>. I am your autonomous physical performance layer. Provide telemetry inputs or query profiles directly.</div></div>';
}

function checkAuth(){
  if(currentUsername){
    eid('auth-overlay').style.display='none';
    var formattedName = currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1);
    eid('uname').textContent = formattedName;
    eid('uav').textContent = currentUsername[0].toUpperCase();
    showWelcomeMessage();
    loadHist();
  } else {
    eid('auth-overlay').style.display='flex';
  }
}

eid('auth-submit-btn').addEventListener('click', function(){
  var u = eid('auth-user').value.trim();
  var p = eid('auth-pass').value;
  if(!u || !p) { eid('auth-error-msg').textContent = 'Fill in all fields'; return; }
  
  fetch('/auth', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:u, password:p})})
  .then(function(r){return r.json();}).then(function(data){
    if(data.success){
      currentUsername = data.username;
      localStorage.setItem('prism_user', currentUsername);
      eid('auth-error-msg').textContent = '';
      checkAuth();
    } else {
      eid('auth-error-msg').textContent = data.error;
    }
  }).catch(function(){ eid('auth-error-msg').textContent = 'Server auth connection error'; });
});

eid('logout-btn').addEventListener('click', function(){
  localStorage.removeItem('prism_user');
  currentUsername = '';
  location.reload();
});

function saveCurrentChat(cb){
  if(!currentUsername) {if(cb)cb(); return;}
  var msgs=[];
  eid('msgs').querySelectorAll('.mg').forEach(function(el){
    var role=el.classList.contains('user')?'user':'agent';
    var b=el.querySelector('.bbl');
    if(b)msgs.push({role:role,text:b.innerText});
  });
  // Avoid saving a bare template message string
  if(msgs.length<=1){if(cb)cb();return;}
  var fu=msgs.find(function(m){return m.role==='user';});
  var title=fu?fu.text.slice(0,42):'Chat';
  
  var payload = {
    username: currentUsername,
    title: title,
    messages: msgs,
    tools_called: currentChatToolsCalled
  };
  if(activeChatId) {
    payload.chat_id = activeChatId;
  }
  
  fetch('/save_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
  .then(function(r){return r.json();}).then(function(data){
    if(data.success && data.chat_id) {
      activeChatId = data.chat_id;
    }
    loadHist();
    if(cb)cb();
  })
  .catch(function(){if(cb)cb();});
}

function newChat(){
  // Clear identity tag instantly before transaction to eliminate ghosting creation loops
  activeChatId = null;
  currentChatToolsCalled=[];
  hist=[];
  showWelcomeMessage();
  resetStats();
  eid('hist-list').querySelectorAll('.hist-item').forEach(function(el){el.classList.remove('active');});
  closeUmenu();
}

function resetStats(){
  eid('v-sl').innerHTML='&#8212;<span class="u">h</span>';
  eid('v-so').innerHTML='&#8212;<span class="u">/10</span>';
  eid('v-en').innerHTML='&#8212;<span class="u">/10</span>';
  eid('v-cal').innerHTML='&#8212;<span class="u">kcal</span>';
  eid('v-wrk').textContent='Not planned yet';
  ['sl','so','en'].forEach(function(k){eid('f-'+k).style.width='0%';});
}

function loadHist(){
  if(!currentUsername) return;
  fetch('/get_chats?username='+encodeURIComponent(currentUsername)).then(function(r){return r.json();}).then(function(data){
    if(!data.chats||data.chats.length===0){
      eid('hist-list').innerHTML='<div style="font-size:11px;color:var(--tx3);padding:4px 3px;font-family:\'JetBrains Mono\'">No local history</div>';
      eid('see-more-btn').style.display = 'none';
      return;
    }
    allChats = data.chats;
    renderHistItems();
  }).catch(function(){});
}

function renderHistItems(){
  var el=eid('hist-list');
  el.innerHTML='';
  var limit = showAllChats ? allChats.length : Math.min(5, allChats.length);
  
  for(var i=0; i<limit; i++){
    (function(){
      var c = allChats[i];
      var div=document.createElement('div');
      div.className='hist-item';
      if(activeChatId === c.id) div.className += ' active';
      div.setAttribute('data-id',c.id);
      var d=new Date(c.created_at);
      var lbl=d.toLocaleDateString('en-IN',{day:'numeric',month:'short'});
      
      div.innerHTML='<div class="hist-info"><div class="hist-title">'+esc(c.title)+'</div><div class="hist-date">'+lbl+' &middot; '+c.messages.length+' msgs</div></div>' +
                    '<button class="hist-del" title="Delete chat">&times;</button>';
      
      div.addEventListener('click', function(e){
        if(e.target.classList.contains('hist-del')) return;
        loadChat(c.id, c.messages, c.tools_called || []);
      });
      
      div.querySelector('.hist-del').addEventListener('click', function(e){
        e.stopPropagation();
        if(confirm("Permanently delete this chat history?")){
          deleteChatFromServer(c.id);
        }
      });
      el.appendChild(div);
    })();
  }
  
  var sm = eid('see-more-btn');
  if(allChats.length > 5){
    sm.style.display = 'block';
    sm.textContent = showAllChats ? 'Show less' : 'See older chats (' + (allChats.length - 5) + ')';
  } else {
    sm.style.display = 'none';
  }
}

function deleteChatFromServer(id){
  fetch('/delete_chat/'+id+'?username='+encodeURIComponent(currentUsername), {method:'DELETE'})
  .then(function(r){return r.json();})
  .then(function(data){
    if(data.success){
      if(activeChatId === id) {
        newChat();
      }
      allChats = allChats.filter(function(c){return c.id !== id;});
      renderHistItems();
    }
  }).catch(function(){});
}

function loadChat(id, messages, tools_called){
  activeChatId = id;
  currentChatToolsCalled = tools_called || [];
  resetStats();
  
  // Reconstruct sidebar stats instantly from the chat thread text if structured tool context logs are hidden
  if(currentChatToolsCalled && currentChatToolsCalled.length) {
     updateStats(currentChatToolsCalled);
  } else {
     parseAndExtractStatsFromMessages(messages);
  }
  
  var msgsEl=eid('msgs');
  msgsEl.innerHTML='';
  messages.forEach(function(m){
    var mg=document.createElement('div');
    mg.className='mg '+(m.role==='user'?'user':'agent');
    var displayName = m.role === 'user' ? (currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1)) : 'Prism';
    mg.innerHTML='<div class="msender">'+displayName+'</div><div class="bbl">'+mdRender(m.text)+'</div>';
    msgsEl.appendChild(mg);
  });
  msgsEl.scrollTop=msgsEl.scrollHeight;
  
  eid('hist-list').querySelectorAll('.hist-item').forEach(function(el){el.classList.remove('active');});
  var a=eid('hist-list').querySelector('[data-id="'+id+'"]');
  if(a)a.classList.add('active');
}

function parseAndExtractStatsFromMessages(messages){
  // Text pattern scanning engine to look for logged metrics within previous messages
  var parsedTools = [];
  messages.forEach(function(m){
    if(m.role === 'agent' || m.role === 'model'){
      var txt = m.text || "";
      if(txt.includes("Logged:") && txt.includes("sleep")){
         var slM = txt.match(/Logged:\s*([0-9.]+)\s*h\s*sleep/i);
         var soM = txt.match(/([0-9.]+)\s*\/10\s*soreness/i);
         var enM = txt.match(/([0-9.]+)\s*\/10\s*energy/i);
         if(slM || soM || enM){
           parsedTools.push({
             name: 'log_daily_state',
             args: {
               sleep_hours: slM ? parseFloat(slM[1]) : 0,
               soreness_level: soM ? parseInt(soM[1]) : 0,
               energy_level: enM ? parseInt(enM[1]) : 0
             }
           });
         }
      }
      if(txt.includes("Workout saved:")){
         var wrkM = txt.match(/Workout saved:\s*'([^']+)'\s*for\s*([0-9]+)\s*mins/i);
         if(wrkM){
           parsedTools.push({
             name: 'update_workout',
             args: { protocol: wrkM[1], duration_mins: parseInt(wrkM[2]) }
           });
         }
      }
      if(txt.includes("Meal plan saved:")){
         var calM = txt.match(/Meal plan saved:\s*([0-9]+)\s*kcal/i);
         if(calM){
           parsedTools.push({
             name: 'log_meal_plan',
             args: { calories: parseInt(calM[1]) }
           });
         }
      }
    }
  });
  if(parsedTools.length > 0) {
    updateStats(parsedTools);
  }
}

function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function updateStats(tools){
  tools.forEach(function(t){
    if(t.name==='log_daily_state'){
      var s=t.args.sleep_hours,so=t.args.soreness_level,en=t.args.energy_level;
      eid('v-sl').innerHTML=s+'<span class="u">h</span>';
      eid('v-so').innerHTML=so+'<span class="u">/10</span>';
      eid('v-en').innerHTML=en+'<span class="u">/10</span>';
      eid('f-sl').style.width=Math.min((s/10)*100,100)+'%';
      eid('f-so').style.width=(so*10)+'%';
      eid('f-en').style.width=(en*10)+'%';
    }
    if(t.name==='update_workout')eid('v-wrk').textContent=t.args.protocol+' \u00B7 '+t.args.duration_mins+' min';
    if(t.name==='log_meal_plan')eid('v-cal').innerHTML=t.args.calories+'<span class="u">kcal</span>';
  });
}

function mdRender(text){
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*([^*\n]+?)\*/g,'<em>$1</em>')
    .replace(/^#{1,3} (.+)$/gm,'<h3>$1</h3>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/^[-*] (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*<\/li>)/g,'<ul>$1</ul>')
    .replace(/<\/ul><ul>/g,'')
    .replace(/\n\n+/g,'</p><p>')
    .replace(/\n/g,'<br>');
}

function handleImageSelect(e){
  var file = e.target.files[0];
  if(!file) return;
  attachedImageMime = file.type;
  var reader = new FileReader();
  reader.onload = function(evt){
    attachedImageBase64 = evt.target.result;
    eid('img-preview').src = attachedImageBase64;
    eid('img-name').textContent = file.name;
    eid('img-prev-wrap').style.display = 'flex';
  };
  reader.readAsDataURL(file);
}

function removeAttachedImage(){
  attachedImageBase64 = null; attachedImageMime = null; eid('img-input').value = ''; eid('img-prev-wrap').style.display = 'none';
}

function openAnalytics(){
  eid('anmodal').style.display = 'flex';
  fetch('/analytics?username='+encodeURIComponent(currentUsername)).then(function(r){return r.json();}).then(function(data){
    if(!data.analytics || data.analytics.length === 0) return;
    var labels = data.analytics.map(function(d){ var p = d.date.split('-'); return p[2] + '/' + p[1]; });
    var sleepVals = data.analytics.map(function(d){return d.sleep;});
    var energyVals = data.analytics.map(function(d){return d.energy;});
    var weightVals = data.analytics.map(function(d){return d.weight;});
    var isDark = !document.body.classList.contains('light');
    var gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)';
    var textColor = isDark ? '#8892a8' : '#5a6280';
    if(healthChart) healthChart.destroy();
    if(weightChart) weightChart.destroy();
    healthChart = new Chart(eid('chart-health').getContext('2d'), {
      type: 'line',
      data: { labels: labels, datasets: [
        { label: 'Sleep (Hours)', data: sleepVals, borderColor: '#5b8def', backgroundColor: 'rgba(91,141,239,0.08)', tension: 0.25, yAxisID: 'y' },
        { label: 'Energy (1-10)', data: energyVals, borderColor: '#3ecf8e', backgroundColor: 'rgba(62,207,142,0.08)', tension: 0.25, yAxisID: 'y1' }
      ]},
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: textColor, font: { family: 'Inter', size: 11 } } } },
        scales: { x: { grid: { color: gridColor }, ticks: { color: textColor } }, y: { position: 'left', min: 0, max: 12, grid: { color: gridColor }, ticks: { color: textColor } }, y1: { position: 'right', min: 0, max: 10, grid: { drawOnChartArea: false }, ticks: { color: textColor } } }
      }
    });
    weightChart = new Chart(eid('chart-weight').getContext('2d'), {
      type: 'line',
      data: { labels: labels, datasets: [{ label: 'Weight (kg)', data: weightVals, borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,0.08)', tension: 0.25, spanGaps: true }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { color: textColor, font: { family: 'Inter', size: 11 } } } }, scales: { x: { grid: { color: gridColor }, ticks: { color: textColor } }, y: { grid: { color: gridColor }, ticks: { color: textColor } } } }
    });
  }).catch(function(){});
}

function sendMsg(){
  var inpEl=eid('inp'); var msg=inpEl.value.trim(); var btn=eid('sbtn');
  if(!msg && !attachedImageBase64) return;
  if(btn.hasAttribute('disabled'))return;
  var curImgBase64 = attachedImageBase64, curImgMime = attachedImageMime;
  inpEl.value=''; inpEl.style.height='auto'; btn.setAttribute('disabled',''); removeAttachedImage();
  var msgsEl=eid('msgs'); var ug=document.createElement('div'); ug.className='mg user';
  var userHtml = '<div class="msender">'+(currentUsername.charAt(0).toUpperCase() + currentUsername.slice(1))+'</div><div class="bbl">';
  if(curImgBase64) userHtml += '<img src="'+curImgBase64+'" style="max-width:240px; max-height:180px; border-radius:8px; margin-bottom:8px; display:block; object-fit:cover;">';
  userHtml += esc(msg || "Analyze image input") + '</div>';
  ug.innerHTML = userHtml; msgsEl.appendChild(ug);
  var tg=document.createElement('div'); tg.className='mg agent';
  tg.innerHTML='<div class="msender">Prism</div><div class="thinking"><div class="dots"><span></span><span></span><span></span></div>Thinking</div>';
  msgsEl.appendChild(tg); msgsEl.scrollTop=msgsEl.scrollHeight;
  
  var reqPayload = {username: currentUsername, message:msg, history:hist};
  if(curImgBase64) { reqPayload.image_base64 = curImgBase64; reqPayload.image_mime = curImgMime; }
  
  fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(reqPayload)})
  .then(function(r){return r.json();}).then(function(data){
    tg.remove(); var ag=document.createElement('div'); ag.className='mg agent';
    var html='<div class="msender">Prism</div><div class="bbl">'+mdRender(data.reply)+'</div>';
    if(data.tools_called&&data.tools_called.length){
      html+='<div class="tbadges">'+data.tools_called.map(function(t){return '<div class="tbadge">'+t.name.replace(/_/g,' ')+'</div>';}).join('')+'</div>';
      updateStats(data.tools_called);
      currentChatToolsCalled = currentChatToolsCalled.concat(data.tools_called);
    }
    ag.innerHTML=html; msgsEl.appendChild(ag); msgsEl.scrollTop=msgsEl.scrollHeight;
    hist.push({role:'user',parts:[{text:msg || "Analyze image input"}]}); hist.push({role:'model',parts:[{text:data.reply}]});
    
    // Auto sync state updates downstream 
    saveCurrentChat();
  }).catch(function(){ tg.innerHTML='<div class="msender">Prism</div><div class="bbl">Network timeout error.</div>'; }).finally(function(){ btn.removeAttribute('disabled'); eid('inp').focus(); });
}

function autoResize(){ var el=eid('inp'); el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,150)+'px'; }
function qa(t){ eid('inp').value=t; autoResize(); sendMsg(); }

function init(){
  checkAuth();
  applyTheme(localStorage.getItem('ptheme')||'dark');
  eid('sbtoggle').addEventListener('click',toggleSb);
  eid('thsw').addEventListener('click',toggleTheme);
  eid('newchatbtn').addEventListener('click',newChat);
  eid('anbtn').addEventListener('click',openAnalytics);
  eid('close-an').addEventListener('click',function(){eid('anmodal').style.display='none';});
  eid('img-input').addEventListener('change',handleImageSelect);
  eid('img-remove').addEventListener('click',removeAttachedImage);
  eid('ucard').addEventListener('click',function(e){e.stopPropagation();toggleUmenu();});
  eid('clear-btn').addEventListener('click',newChat);
  eid('sbtn').addEventListener('click',sendMsg);
  eid('inp').addEventListener('input',autoResize);
  eid('inp').addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}});
  eid('see-more-btn').addEventListener('click', function(){ showAllChats = !showAllChats; renderHistItems(); });
  
  eid('q1').addEventListener('click',function(){qa('Log that I drank 4 glasses of water');});
  eid('q2').addEventListener('click',function(){qa('Show me my weekly progress summary');});
  eid('q3').addEventListener('click',function(){qa('Give me a high protein vegetarian Indian meal plan for today');});
  eid('q4').addEventListener('click',function(){qa('What supplements help with muscle gain and recovery?');});
  eid('q5').addEventListener('click',function(){qa('I am feeling very tired today, what should I do?');});
  eid('q6').addEventListener('click',function(){qa('Explain how to do a proper bench press with correct form');});
  document.addEventListener('click',function(e){ if(!e.target.closest('#ucard')&&!e.target.closest('#umenu'))closeUmenu(); });
}
document.addEventListener('DOMContentLoaded',init);
})();
</script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

