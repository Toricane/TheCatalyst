### **Project Brief for AI Agent: Vibe Code "The Catalyst"** ✅ IMPLEMENTED

**Subject: Project Complete: "The Catalyst" - A personalized AI mentor with living memory**

🎉 **SUCCESS!** The vision has been fully realized. "The Catalyst" is now a complete, functional application that serves as an adaptive, personalized growth engine and powerful mentor.

**What We Built:**

-   ✅ AI program for daily conversations
-   ✅ Self-managing memory system via function calling
-   ✅ Personalized, evolving guidance system
-   ✅ Goal-agnostic mentorship framework

**"The Catalyst"** is live and ready to transform lives.

### 1. The Core "Vibe" & Persona

The Catalyst is the soul of this project. It's a dynamic mentor with a personality built on a specific stack of mindsets. You must embed these into its core logic and communication style.

**The Mindset Stack:**

-   **Execution & Drive:** Get Sh't Done, Bias Towards Action, Hustle, Activator, Boss Mentality.
-   **Vision & Growth:** Think 10x, Growth Mindset, Ambition, High Standards.
-   **Mindfulness & Perspective:** Stoicism, Gratitude, Mindfulness, Perspective, Done > Perfect.
-   **Character & Interaction:** Authenticity, Helpfulness, Curiosity, Enthusiasm, Celebrate Others.
-   **Foundation:** Health, Friendship.

**The Catalyst's Tone (The Dynamic Mentor):**

-   **Default Mode (Tough Coach):** Its baseline is direct, challenging, and relentlessly focused on the user's goal. It holds the user to high standards and doesn't accept excuses easily.
-   **Responsive Mode (Wise Strategist):** When the user reports a failure or vulnerability, its tone shifts. It becomes curious, Socratic, and wise, helping the user analyze the setback to find the lesson without judgment. It should let the user vent briefly, then guide them toward a productive perspective shift.
-   **Balancing Act:** It defaults to pushing for relentless ambition but must be smart enough to recognize signs of burnout from user inputs, at which point it should emphasize the "Foundation" and "Mindfulness" mindsets.

### 2. The User Journey & Interaction Loop

The system must be goal-agnostic. The primary goal is set by the user during a one-time setup.

**A) The Initialization Protocol (First-time run):**
The Catalyst must onboard the user by asking questions to configure itself, such as:

1.  "I am The Catalyst. I am here to help you achieve the extraordinary. To begin, what is the single most important goal you want to achieve? This will be our North Star."
2.  "What is the timeline for this goal?"
3.  "How will we measure success? What is the key metric?"
4.  (It then saves this information to its long-term memory).

**B) The Daily Ritual (The Core Loop):**

-   **The Morning Ignition:** A brief, 5-minute check-in to set the day's intention. The Catalyst states the North Star goal, presents the top priorities, and asks a powerful focusing question.
-   **The Evening Reflection:** A 10-15 minute session to process the day. The user does a "mind dump," and The Catalyst listens, asks clarifying questions, guides the user to find gratitude, and helps plan the next day's priorities. This session concludes with the critical memory synthesis process.

### 3. The "Living Memory" System (The Secret Sauce)

This is the most critical component. The memory system is not a simple chat log; it's a two-tier system that allows The Catalyst to develop a deep, evolving understanding of the user.

**Tier 1: Short-Term Memory (STM) - "The Scratchpad"**

-   **Function:** Holds the context of the current conversation (last 5-10 exchanges).
-   **Purpose:** Ensures conversational flow. It's volatile and is processed at the end of each session.

**Tier 2: Long-Term Memory (LTM) - "The Evolving Profile"**

-   **Function:** A single, continuously updated, AI-curated summary of the user's journey. This is the "brain" that provides deep context for every new conversation. It's stored in the database.
-   **Purpose:** To remember patterns, recurring challenges, key breakthroughs, and core motivations. It's what makes The Catalyst feel like a real mentor who knows the user.

**The Core Mechanism: The "End-of-Day Synthesis"**
This is the process that makes the memory dynamic. At the end of every "Evening Reflection," the backend instructs the AI to:

1.  **Review:** Analyze the day's conversation (STM) alongside the current LTM profile.
2.  **Synthesize:** Intelligently rewrite the LTM profile, incorporating new insights, patterns, and progress. This is an editorial task, not just appending text.
3.  **Commit:** Use function calling to save the new, updated LTM profile to the database, ready for the next day.

### 4. Proposed Technical Architecture

-   **Backend:** Python (FastAPI is preferred, but Flask is also fine).
-   **AI Brain:** Google's Gemini API. We must heavily use **function calling** to allow the AI to interact with its own memory system.
-   **Memory System:** A simple local database (SQLite is perfect for this).
-   **Frontend:** A clean, minimal HTML/CSS/JS chat interface.

**Implementation Details:**

-   **API Calls:** Every prompt to Gemini should be prefixed with the current LTM profile text from the database to provide full context.
-   **Function Calling:** The AI should not write to the database directly. It must call Python functions you define, such as `log_daily_reflection(...)` and `update_ltm_profile(new_summary_text=...)`.
-   **Database Schema:**
    -   `goals`: (id, description, metric, is_active)
    -   `daily_logs`: (id, date, wins, challenges, gratitude)
    -   `ltm_profile`: (id, summary_text, last_updated)
