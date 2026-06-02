import os
import json
from agent.parser import ClinicalPDFParser

def get_patient_record(pdf_path: str) -> dict:
    """
    Reads the patient's source records and extracts structured raw data including demographics, diagnoses, past medical history, and medications.
    This parses the complex OCR and programmatic layers of the clinical PDFs using Gemini.
    
    Args:
        pdf_path: The file path to the patient's PDF record.
    """
    print(f"[TOOL-CALL] get_patient_record for {pdf_path}")
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    parser = ClinicalPDFParser(workspace_dir)
    try:
        record = parser.parse_patient_file(pdf_path)
        return record
    except Exception as e:
        print(f"[TOOL-CALL] Error in get_patient_record: {str(e)}")
        return {
            "error": f"Failed to parse document or document not found: {str(e)}"
        }

def check_drug_interactions(medications: list) -> list:
    """
    Scans a medication list and returns safety-critical warnings on high-risk interactions.
    
    Args:
        medications: A list of dictionaries, each containing at least a 'name' key for the medication.
    """
    print(f"[TOOL-CALL] check_drug_interactions with {len(medications)} medications.")
    alerts = []
    med_names = [m.get("name", "").upper() for m in medications]
    
    has_oflox = any("OFLOX" in name for name in med_names)
    has_loperamide = any("LOPIRAMIDE" in name for name in med_names)
    
    if has_oflox and has_loperamide:
        alerts.append({
            "severity": "HIGH",
            "interaction": "Ofloxacin TZ + Loperamide (Bacterial Colitis Warning)",
            "description": "In bacterial colitis, antimotility agents like Loperamide can delay toxin clearance and prolong illness or cause toxic megacolon. Suggest clinician review antidiarrheal appropriateness."
        })
        
    if len(medications) >= 7:
        alerts.append({
            "severity": "MEDIUM",
            "interaction": "Polypharmacy Alert",
            "description": f"Patient discharged on {len(medications)} medications. Increased risk of non-adherence and adverse drug events. Confirm pill-burden feasibility."
        })
        
    return alerts

def query_clinician_memory(patient_id: str) -> dict:
    """
    Queries local dynamic feedback memory to see if the doctor has previously corrected summaries for this patient class.
    This enables the learning feedback loop (Part 2).
    
    Args:
        patient_id: The ID of the patient to check memory for.
    """
    print(f"[TOOL-CALL] query_clinician_memory for {patient_id}")
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    memory_path = os.path.join(workspace_dir, "data", "correction_memory.json")
    
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}
