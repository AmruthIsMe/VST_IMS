"""
Standalone runner for SAP Mock ERP Server.
Usage: python run_sap_erp.py
"""
import uvicorn
import os
import sys

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from server import app
    print("=" * 60)
    print("  SAP Mock ERP Server")
    print("  Port: 8001")
    print("  Web UI: http://localhost:8001")
    print("  API Docs: http://localhost:8001/docs")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8001)
