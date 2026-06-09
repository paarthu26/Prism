# Prism — Elite Performance Coaching Layer

Prism is an autonomous physical performance and health optimization dashboard. It features a sleek telemetry sidebar to track biometrics alongside an intelligent AI agent capable of multi-turn conversational context, autonomous function calling for health metrics, and comprehensive diagnostic charting.

# Key Features

* **Real-Time Telemetry Tracking:** Dynamic visual baselines tracking Sleep hours, Soreness levels, Energy output, and Water intake.
* **Autonomous AI Coach:** Driven by Gemini 2.5 Flash with function-calling capabilities to update and write health metrics directly to the user data layer.
* **Timeline Context Persistency:** Secure user token authentication and continuous session history serialization.
* **Quick Ask Tools:** Rapid shortcut actions handling user routines, supplements tracking, meal planning, and posture form checking.


# Tech Stack

* **Backend Framework:** FastAPI (Python 3.10+)
* **Database Layer:** Google Cloud Firestore (NoSQL Document Store)
* **AI Core Engine:** Gemini 2.5 Flash via Vertex AI SDK
* **Frontend Design:** Vanilla HTML5, Responsive CSS3, Native Asynchronous JavaScript

## ⚙️ Setup & Run Instructions

# Prerequisites
* Python 3.10 or higher installed locally.
* A Google Cloud Platform (GCP) project with the Firestore API and Vertex AI API enabled.
* Application Default Credentials configured locally via Google Cloud CLI (`gcloud auth application-default login`).

# Installation & Local Launch

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/paarthu26/Prism.git](https://github.com/paarthu26/Prism.git)
   cd Prism

* **Partner Track Integration:** MongoDB Atlas (Target production data store for handling high-throughput JSON document biometrics, flexible telemetry arrays, and multi-turn AI session histories).
