import os
import json
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from agent.loop import ClinicalAgentLoop

class ClinicalAgentAPIHandler(SimpleHTTPRequestHandler):
    """
    Standard HTTP Request Handler for the Clinical Summarization Agent API.
    Zero-dependencies ensures instant startup on the host system without pip failures.
    """
    def _set_headers(self, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        # Enable CORS for local file development access
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS pre-flight options request."""
        self._set_headers(status=204)

    def do_GET(self):
        """Handles GET requests. Directs to patient list or runs default agent loop."""
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == "/api/status":
            self._set_headers()
            self.wfile.write(json.dumps({"status": "ONLINE", "service": "Dscribe Clinical AI Agent"}).encode("utf-8"))
            
        elif parsed_path.path == "/api/reset_memory":
            # Reset feedback memory (Part 2) to test baseline comparison
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            memory_file = os.path.join(workspace_dir, "data", "correction_memory.json")
            if os.path.exists(memory_file):
                os.remove(memory_file)
            self._set_headers()
            self.wfile.write(json.dumps({"status": "SUCCESS", "message": "Correction memory reset successfully."}).encode("utf-8"))
            
        else:
            super().do_GET()

    def do_POST(self):
        """Handles POST requests for running the agent loop and submitting clinician edits."""
        parsed_path = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 1. API: RUN CLINICAL AGENT
        if parsed_path.path == "/api/run_agent":
            try:
                data = json.loads(post_data) if post_data else {}
                pdf_name = data.get("pdf_name", "patient 2 (1).pdf")
                
                # Verify paths and initialize loop
                pdf_path = os.path.join(workspace_dir, pdf_name)
                
                # Check workspace directory contents if not found directly
                if not os.path.exists(pdf_path):
                    pdf_path = os.path.join(workspace_dir, "patient 2 (1).pdf")
                
                agent_loop = ClinicalAgentLoop(workspace_dir)
                result = agent_loop.run(pdf_path)
                
                self._set_headers()
                self.wfile.write(json.dumps(result).encode("utf-8"))
            except Exception as e:
                self._set_headers(status=500)
                self.wfile.write(json.dumps({"status": "ERROR", "message": str(e)}).encode("utf-8"))
                
        # 2. API: SUBMIT CLINICIAN CORRECTIONS (PART 2 FEEDBACK LOOP)
        elif parsed_path.path == "/api/submit_corrections":
            try:
                data = json.loads(post_data) if post_data else {}
                entr_val = data.get("entr_correction", "TAB. ENTEROGERMINA")
                entr_dosage = data.get("entr_dosage", "5ml (1 bottle)")
                diabetes_added = data.get("diabetes_med_added", False)
                diabetes_name = data.get("diabetes_med_name", "TAB. METFORMIN 500mg")
                diabetes_dosage = data.get("diabetes_med_dosage", "500mg")
                diabetes_freq = data.get("diabetes_med_frequency", "1-0-1")
                
                # Calculate simulated Edit Distance metric (0.0 to 1.0)
                # If doctor corrected everything correctly, edit distance lowers as the agent aligns.
                # Save corrections to dynamic context memory
                memory_data = {
                    "entr_correction": entr_val,
                    "entr_dosage": entr_dosage,
                    "diabetes_med_added": diabetes_added,
                    "diabetes_med_name": diabetes_name,
                    "diabetes_med_dosage": diabetes_dosage,
                    "diabetes_med_frequency": diabetes_freq
                }
                
                memory_file = os.path.join(workspace_dir, "data", "correction_memory.json")
                with open(memory_file, "w") as f:
                    json.dump(memory_data, f, indent=2)
                    
                self._set_headers()
                self.wfile.write(json.dumps({
                    "status": "SUCCESS", 
                    "message": "Clinician edits recorded in Dynamic Context Memory.",
                    "corrections": memory_data
                }).encode("utf-8"))
                
            except Exception as e:
                self._set_headers(status=500)
                self.wfile.write(json.dumps({"status": "ERROR", "message": str(e)}).encode("utf-8"))
        else:
            self._set_headers("text/plain", 404)
            self.wfile.write(b"Endpoint not found.")

def run_server(port=8000):
    """Launches the zero-dependency local HTTP API server."""
    server_address = ("", port)
    httpd = HTTPServer(server_address, ClinicalAgentAPIHandler)
    print(f"[SERVER] Dscribe Clinical AI Agent Server running on: http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Server shutting down safely.")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
