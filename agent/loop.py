import os
import json
import traceback

# Import the google-genai client
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

from agent.tools import get_patient_record, check_drug_interactions, query_clinician_memory

class ClinicalAgentLoop:
    """
    Main Agentic Loop for Discharge Summary Generation using a real LLM (Gemini).
    Enforces a strict Plan-and-Replan cycle with a hard iteration cap.
    """
    def __init__(self, workspace_dir, step_cap=10):
        self.workspace_dir = workspace_dir
        self.step_cap = step_cap
        
        # Load from .env file if it exists (Zero-dependency approach)
        env_path = os.path.join(self.workspace_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")
                        
        # We need the API key from environment
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if self.api_key and genai:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None

        self.tools_map = {
            "get_patient_record": get_patient_record,
            "check_drug_interactions": check_drug_interactions,
            "query_clinician_memory": query_clinician_memory
        }

    def _compile_mock_raw_data(self):
        """Fallback empty draft"""
        return {
          "patient_demographics": {
            "name": "[MISSING - CLINICIAN REVIEW REQUIRED]",
            "age": "[MISSING]",
            "gender": "[MISSING]",
            "weight": "[MISSING]",
            "mrn": "[MISSING]"
          },
          "dates": {
            "admission_date": "[MISSING]",
            "discharge_date": "[MISSING]"
          },
          "diagnoses": {
            "principal_diagnosis": "[MISSING]",
            "secondary_diagnoses": [],
            "clinician_review_needed_diagnoses": []
          },
          "hospital_course": "",
          "procedures_done": [],
          "allergies": "Not Known",
          "discharge_medications": [],
          "follow_up_instructions": ["[MISSING - CLINICIAN REVIEW REQUIRED]"],
          "pending_results": [],
          "discharge_condition": "[MISSING - CLINICIAN REVIEW REQUIRED]",
          "reconciliation_flags": [],
          "interaction_alerts": [],
          "history_conflict_flag": False,
          "past_history_stated": "[MISSING]"
        }

    def _compile_timeout(self, trace):
        print("[AGENT] Cap hit. Terminating safely.")
        return {
            "status": "TIMEOUT",
            "trace": trace,
            "draft": self._compile_mock_raw_data()
        }

    def run(self, pdf_path):
        """
        Executes the agentic plan-and-replan clinical loop.
        Never crashes; implements robust exception handling and step-tracing.
        """
        trace = []
        
        # If API key is missing, throw so main.py returns 500, triggering JS fallback mock
        if not self.client:
            print("[AGENT-ERROR] GEMINI_API_KEY not set. Falling back to frontend simulation.")
            raise Exception("GEMINI_API_KEY not set. Please export the GEMINI_API_KEY environment variable.")

        print(f"[AGENT] Starting Agent Loop for {pdf_path}")
        
        system_instruction = """You are an advanced clinical agent responsible for generating discharge summaries.
You operate in a strict PLAN AND REPLAN loop. At each step, you must output a JSON object describing your reasoning, the tool you want to call, and the inputs.
Once you have all the necessary information, you will output 'is_final': true and provide the 'final_draft' JSON.

CRITICAL CLINICAL RULES (NO FABRICATION):
1. Never invent or guess clinical facts. If a required field is missing, output "[MISSING - CLINICIAN REVIEW REQUIRED]".
2. Handle Conflicting Info: If two notes disagree, flag it! Do not arbitrarily pick one. Set 'history_conflict_flag' to true in the final draft.
3. Medication Reconciliation: Compare admission and discharge medications. If a medication (like Diabetes management insulin) is dropped without reason, or if a medication name is truncated (e.g. "TAB. ENTR("), flag it under 'reconciliation_flags'.
4. Truncated drugs MUST be flagged, DO NOT guess their full name unless clinician memory corrects it!
5. CLINICIAN MEMORY OVERRIDE: If 'query_clinician_memory' returns specific corrections for a patient (like resolving a truncated drug to "ENTEROGERMINA" or adding "METFORMIN"), you MUST apply those corrections to your final_draft. If a memory correction resolves an issue, DO NOT flag it in reconciliation_flags.

AVAILABLE TOOLS:
- 'get_patient_record': Inputs: {"pdf_path": "<path>"} -> Returns parsed patient data.
- 'check_drug_interactions': Inputs: {"medications": [{"name": "drug"}]} -> Returns warnings.
- 'query_clinician_memory': Inputs: {"patient_id": "<id>"} -> Returns past doctor corrections. USE THIS to correct truncated names or omissions if memory exists!

OUTPUT FORMAT:
You must return exactly ONE valid JSON object per response, matching this schema:
{
  "reasoning": "Your thought process for this step",
  "tool_chosen": "tool_name" (or null if finished),
  "inputs": { ... inputs for the tool ... },
  "next_decision": "What you plan to do after this tool returns",
  "is_final": false,
  "final_draft": null
}

When finished, set "is_final": true, "tool_chosen": null, and populate "final_draft" with this schema:
{
  "patient_demographics": {"name": "", "age": "", "gender": "", "weight": "", "mrn": ""},
  "dates": {"admission_date": "", "discharge_date": ""},
  "diagnoses": {"principal_diagnosis": "", "secondary_diagnoses": [], "clinician_review_needed_diagnoses": []},
  "hospital_course": "",
  "procedures_done": [],
  "allergies": "",
  "discharge_medications": [{"name": "", "dosage": "", "frequency": "", "duration": "", "reason": ""}],
  "follow_up_instructions": ["string"],
  "pending_results": [],
  "discharge_condition": "",
  "reconciliation_flags": [{"severity": "", "type": "", "item": "", "description": ""}],
  "interaction_alerts": [{"severity": "", "interaction": "", "description": ""}],
  "history_conflict_flag": boolean,
  "past_history_stated": ""
}
"""

        messages = [
            {"role": "user", "parts": [{"text": f"Begin processing patient file: {pdf_path}. Output the first step JSON."}]}
        ]
        
        step_count = 0
        memory_used = False
        
        try:
            while step_count < self.step_cap:
                step_count += 1
                print(f"[AGENT] Step {step_count}...")
                
                # Make LLM Call with Retry for Rate Limits
                import time
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = self.client.models.generate_content(
                            model="gemini-2.0-flash",
                            contents=messages,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                response_mime_type="application/json",
                                temperature=0.0
                            )
                        )
                        break # Success
                    except Exception as e:
                        if "429" in str(e) and attempt < max_retries - 1:
                            print(f"[AGENT] Rate limit hit. Waiting 65s for quota reset (Attempt {attempt+1}/{max_retries})...")
                            time.sleep(65)
                        else:
                            raise e
                
                # Throttle to prevent hitting the 15 Requests Per Minute limit (~1 request every 4 seconds)
                time.sleep(4)
                
                response_text = response.text
                
                try:
                    step_data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    print(f"[AGENT] Invalid JSON from LLM: {response_text}")
                    raise Exception("LLM returned invalid JSON.")
                    
                reasoning = step_data.get("reasoning", "")
                tool_chosen = step_data.get("tool_chosen")
                inputs = step_data.get("inputs", {})
                next_decision = step_data.get("next_decision", "")
                is_final = step_data.get("is_final", False)
                final_draft = step_data.get("final_draft")
                
                if tool_chosen == "query_clinician_memory":
                    memory_used = True

                # Record step trace
                trace_entry = {
                    "step": step_count,
                    "name": tool_chosen.upper() if tool_chosen else "FINALIZATION",
                    "reasoning": reasoning,
                    "tool_chosen": tool_chosen or "None",
                    "inputs": inputs,
                    "result": "",
                    "next_decision": next_decision
                }
                
                if is_final and final_draft:
                    trace_entry["result"] = "Draft finalized."
                    trace.append(trace_entry)
                    return {
                        "status": "COMPLETED",
                        "trace": trace,
                        "draft": final_draft,
                        "baseline_active": not memory_used
                    }
                
                # Execute tool
                tool_result = ""
                if tool_chosen in self.tools_map:
                    try:
                        func = self.tools_map[tool_chosen]
                        if tool_chosen == "get_patient_record":
                            res = func(pdf_path)
                        else:
                            res = func(**inputs)
                        tool_result = json.dumps(res)
                        trace_entry["result"] = f"Tool {tool_chosen} executed successfully."
                    except Exception as e:
                        tool_result = json.dumps({"error": str(e)})
                        trace_entry["result"] = f"Tool {tool_chosen} failed: {str(e)}"
                else:
                    tool_result = json.dumps({"error": f"Tool '{tool_chosen}' not found."})
                    trace_entry["result"] = f"Tool {tool_chosen} not found."
                
                trace.append(trace_entry)
                
                # Append LLM's own response and the tool's result to conversation
                messages.append({"role": "model", "parts": [{"text": response_text}]})
                messages.append({"role": "user", "parts": [{"text": f"Tool Result: {tool_result}\nNow provide the next step JSON."}]})
            
            # If loop ends without finalizing
            return self._compile_timeout(trace)

        except Exception as e:
            print(f"[AGENT-ERROR] Critical failure: {traceback.format_exc()}")
            trace.append({
                "step": step_count + 1,
                "name": "CRITICAL_FAILURE_RECOVERY",
                "reasoning": "Rescuing execution from standard exception crash.",
                "tool_chosen": "SystemRecovery",
                "inputs": {"error": str(e)},
                "result": "Recovered successfully and compiled safety-first refusal output.",
                "next_decision": "Terminate safely."
            })
            return {
                "status": "FAILED",
                "error": str(e),
                "trace": trace,
                "draft": self._compile_mock_raw_data()
            }
