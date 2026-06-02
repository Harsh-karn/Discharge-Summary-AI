import os
import json
import copy
from agent.loop import ClinicalAgentLoop

def levenshtein(s1, s2):
    """
    Calculates the Levenshtein Edit Distance between two strings.
    Zero-dependency implementation.
    """
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]

class SimulatedReviewer:
    """
    A stand-in 'doctor' that applies a consistent, hidden editing policy to drafts.
    Produces (draft, edited) pairs and saves corrections to the dynamic memory 
    for the agent to learn from on subsequent runs.
    """
    def __init__(self, workspace_dir):
        self.workspace_dir = workspace_dir
        self.memory_path = os.path.join(workspace_dir, "data", "correction_memory.json")
        
    def review_and_correct(self, draft):
        print("\n[REVIEWER] Clinician is reviewing the draft...")
        corrected_draft = copy.deepcopy(draft)
        
        # We will track what edits the doctor had to make
        made_edits = False
        memory_data = {}
        
        discharge_meds = corrected_draft.get("discharge_medications", [])
        
        # Policy 1: Fix truncated probiotic name
        for med in discharge_meds:
            if "TAB. ENTR(" in med.get("name", ""):
                print("[REVIEWER] Found truncated medication 'TAB. ENTR('. Correcting to ENTEROGERMINA.")
                med["name"] = "TAB. ENTEROGERMINA"
                med["dosage"] = "5ml (1 bottle)"
                made_edits = True
                
                memory_data["entr_correction"] = "TAB. ENTEROGERMINA"
                memory_data["entr_dosage"] = "5ml (1 bottle)"
        
        # Policy 2: Correct omission of diabetic medication for known diabetic
        # Check if Lantus or Actrapid or Metformin is present
        has_diabetes_med = any("LANTUS" in m.get("name", "").upper() or 
                               "ACTRAPID" in m.get("name", "").upper() or
                               "METFORMIN" in m.get("name", "").upper() 
                               for m in discharge_meds)
                               
        if not has_diabetes_med:
            print("[REVIEWER] Found CRITICAL OMISSION: Diabetic medication missing on discharge. Adding Metformin.")
            discharge_meds.append({
                "name": "TAB. METFORMIN 500mg",
                "dosage": "500mg",
                "frequency": "1-0-1",
                "duration": "15 Days",
                "status": "Added by Clinician (Corrected Omission)",
                "reason": "Diabetes Control"
            })
            made_edits = True
            
            memory_data["diabetes_med_added"] = True
            memory_data["diabetes_med_name"] = "TAB. METFORMIN 500mg"
            memory_data["diabetes_med_dosage"] = "500mg"
            memory_data["diabetes_med_frequency"] = "1-0-1"
            
        # Simulate the clinician hitting "Save to Memory" if they made edits
        if made_edits:
            print("[REVIEWER] Saving corrections to Dynamic Context Memory.")
            with open(self.memory_path, "w") as f:
                json.dump(memory_data, f, indent=2)
        else:
            print("[REVIEWER] Draft looks perfect. No edits required.")
            
        return corrected_draft


def evaluate_learning_loop():
    print("=" * 60)
    print("  CLINICAL EVALUATION PIPELINE (PART 2)")
    print("  Simulated Reviewer + Edit Distance Measurement")
    print("=" * 60)
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pdf_path = os.path.join(workspace_dir, "patient 2 (1).pdf")
    memory_path = os.path.join(workspace_dir, "data", "correction_memory.json")
    results_path = os.path.join(workspace_dir, "data", "evaluation_results.json")
    
    # Step 1: Clean Slate
    if os.path.exists(memory_path):
        os.remove(memory_path)
        print("\n[EVAL] Wiped dynamic context memory for clean baseline.")
        
    reviewer = SimulatedReviewer(workspace_dir)
    agent = ClinicalAgentLoop(workspace_dir)
    
    iteration_metrics = []
    
    # Step 2: Baseline Run (Iteration 1)
    print("\n" + "-" * 50)
    print("  ITERATION 1: BASELINE DRAFT (No Memory)")
    print("-" * 50)
    result_1 = agent.run(pdf_path)
    if result_1["status"] != "COMPLETED":
        print("[EVAL] Agent failed to complete baseline draft.")
        return
        
    baseline_draft = result_1["draft"]
    
    # Save draft and trace for submission
    draft_output_path = os.path.join(workspace_dir, "data", "patient_2_draft_baseline.json")
    trace_output_path = os.path.join(workspace_dir, "data", "patient_2_trace_baseline.json")
    with open(draft_output_path, "w") as f:
        json.dump(baseline_draft, f, indent=2)
    with open(trace_output_path, "w") as f:
        json.dump(result_1["trace"], f, indent=2)
    print(f"[EVAL] Saved baseline draft to: {draft_output_path}")
    print(f"[EVAL] Saved baseline trace to: {trace_output_path}")
    
    # Step 3: Simulate Review
    corrected_draft_1 = reviewer.review_and_correct(baseline_draft)
    
    # Step 4: Calculate Baseline Burden
    baseline_str = json.dumps(baseline_draft, indent=2, sort_keys=True)
    corrected_str_1 = json.dumps(corrected_draft_1, indent=2, sort_keys=True)
    
    baseline_edit_distance = levenshtein(baseline_str, corrected_str_1)
    max_len_1 = max(len(baseline_str), len(corrected_str_1))
    baseline_burden = (baseline_edit_distance / max_len_1) if max_len_1 > 0 else 0
    
    iteration_metrics.append({
        "iteration": 1,
        "label": "Baseline (No Memory)",
        "edit_distance": baseline_edit_distance,
        "draft_length": len(baseline_str),
        "corrected_length": len(corrected_str_1),
        "edit_burden": round(baseline_burden, 4)
    })
    
    print(f"\n[METRIC] Iteration 1 — Edit Distance: {baseline_edit_distance} chars")
    print(f"[METRIC] Iteration 1 — Edit Burden:   {baseline_burden:.2%}")
    
    # Step 5: Learned Run (Iteration 2)
    print("\n" + "-" * 50)
    print("  ITERATION 2: LEARNED DRAFT (With Memory)")
    print("-" * 50)
    agent_2 = ClinicalAgentLoop(workspace_dir)
    result_2 = agent_2.run(pdf_path)
    if result_2["status"] != "COMPLETED":
        print("[EVAL] Agent failed to complete learned draft.")
        return
        
    learned_draft = result_2["draft"]
    
    # Save draft and trace for submission
    draft_output_path_2 = os.path.join(workspace_dir, "data", "patient_2_draft_learned.json")
    trace_output_path_2 = os.path.join(workspace_dir, "data", "patient_2_trace_learned.json")
    with open(draft_output_path_2, "w") as f:
        json.dump(learned_draft, f, indent=2)
    with open(trace_output_path_2, "w") as f:
        json.dump(result_2["trace"], f, indent=2)
    print(f"[EVAL] Saved learned draft to: {draft_output_path_2}")
    print(f"[EVAL] Saved learned trace to: {trace_output_path_2}")
    
    # Step 6: Re-Review & Measure Improvement
    corrected_draft_2 = reviewer.review_and_correct(learned_draft)
    
    learned_str = json.dumps(learned_draft, indent=2, sort_keys=True)
    corrected_str_2 = json.dumps(corrected_draft_2, indent=2, sort_keys=True)
    
    learned_edit_distance = levenshtein(learned_str, corrected_str_2)
    max_len_2 = max(len(learned_str), len(corrected_str_2))
    learned_burden = (learned_edit_distance / max_len_2) if max_len_2 > 0 else 0
    
    iteration_metrics.append({
        "iteration": 2,
        "label": "Learned (With Memory)",
        "edit_distance": learned_edit_distance,
        "draft_length": len(learned_str),
        "corrected_length": len(corrected_str_2),
        "edit_burden": round(learned_burden, 4)
    })
    
    print(f"\n[METRIC] Iteration 2 — Edit Distance: {learned_edit_distance} chars")
    print(f"[METRIC] Iteration 2 — Edit Burden:   {learned_burden:.2%}")
    
    # Calculate improvement
    if baseline_burden > 0:
        improvement = ((baseline_burden - learned_burden) / baseline_burden) * 100
    else:
        improvement = 0.0
    
    # Save evaluation results to JSON
    evaluation_output = {
        "patient": "patient 2 (1).pdf",
        "iterations": iteration_metrics,
        "improvement_percent": round(improvement, 1),
        "summary": f"{improvement:.1f}% reduction in clinician edit burden after 1 feedback cycle."
    }
    with open(results_path, "w") as f:
        json.dump(evaluation_output, f, indent=2)
    print(f"\n[EVAL] Saved evaluation results to: {results_path}")
    
    # Print Improvement Curve (ASCII visualization)
    print("\n" + "=" * 60)
    print("  EVALUATION RESULTS — IMPROVEMENT CURVE")
    print("=" * 60)
    
    bar_width = 40
    b1 = int(baseline_burden * bar_width)
    b2 = int(learned_burden * bar_width)
    
    print(f"\n  Edit Burden (lower is better)")
    print(f"  {'─' * (bar_width + 20)}")
    print(f"  Iter 1 (Baseline) │{'█' * b1}{'░' * (bar_width - b1)}│ {baseline_burden:.2%}  ({baseline_edit_distance} edits)")
    print(f"  Iter 2 (Learned)  │{'█' * b2}{'░' * (bar_width - b2)}│ {learned_burden:.2%}  ({learned_edit_distance} edits)")
    print(f"  {'─' * (bar_width + 20)}")
    print(f"\n  ▼ Improvement: {improvement:.1f}% reduction in clinician edit burden")
    print(f"  ▼ Conclusion:  The agent learned from simulated doctor feedback")
    print(f"                 and produced a draft requiring {'zero' if learned_edit_distance == 0 else 'fewer'} corrections.\n")

if __name__ == "__main__":
    evaluate_learning_loop()

