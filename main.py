from typing import List, Optional
from fastapi import FastAPI, Depends, status, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field
from datetime import datetime
import requests

# Import database layer modules
from database import engine, Base, get_db
from models import FieldReportModel

Base.metadata.create_all(bind=engine)

app = FastAPI(title="EpiTrack Ethiopia: National Command Center", version="1.0.0")

# --- Native Carrier Configurations ---
ETHIO_TELECOM_URL = "https://ethiotelecom.et"
ETHIO_ENTERPRISE_TOKEN = "ethio_prod_secure_bearer_token"
ETHIO_SHORTCODE = "8044"
SAFARICOM_ET_URL = "https://safaricom.et"
SAFARICOM_API_KEY = "safaricom_et_secure_token"

# --- Validation Schemas ---
class FieldReport(BaseModel):
    woreda: str = Field(..., min_length=2, max_length=50, examples=["Jimma"])
    disease_type: str = Field(..., min_length=3, max_length=50, examples=["Cholera"])
    case_count: int = Field(..., ge=0, le=100000, examples=[6])

class DashboardMetrics(BaseModel):
    active_outbreaks: int
    total_suspected_cases: int
    lab_confirmed_cases: int
    dhis2_transmission_rate: float

class ReportResponse(BaseModel):
    status: str
    alert: bool
    message: str
    sms_draft_en: Optional[str] = ""
    sms_draft_om: Optional[str] = ""
    updated_dashboard: DashboardMetrics

class SavedReportResponse(BaseModel):
    id: int
    woreda: str
    disease_type: str
    case_count: int
    is_alert: bool
    created_at: datetime
    class Config:
        from_attributes = True

# --- Background Telecommunications Core ---
def dispatch_national_telecom_alerts(woreda: str, message_content: str, routing_mode: str = "ethio"):
    target_recipients = ["+251911000000"]
    if routing_mode == "ethio":
        print(f"\n[ETHIO TELECOM] Routing emergency broadcast for {woreda} via Shortcode {ETHIO_SHORTCODE}...")
        payload = {"sender_id": ETHIO_SHORTCODE, "recipients": target_recipients, "message": message_content}
        headers = {"Authorization": f"Bearer {ETHIO_ENTERPRISE_TOKEN}", "Content-Type": "application/json"}
        try:
            response = requests.post(ETHIO_TELECOM_URL, json=payload, headers=headers, timeout=3)
            if response.status_code == 200: return
        except Exception: pass
        routing_mode = "safaricom"

    if routing_mode == "safaricom":
        print(f"\n[SAFARICOM ETHIOPIA] Cascading failover routing for {woreda} initiated...")
        payload = {"to": target_recipients, "message": message_content}
        headers = {"X-Safaricom-API-Key": SAFARICOM_API_KEY, "Content-Type": "application/json"}
        try:
            response = requests.post(SAFARICOM_ET_URL, json=payload, headers=headers, timeout=3)
            if response.status_code == 200: print("✅ [SAFARICOM SUCCESS] Emergency network alert sent."); return
        except Exception: pass

# --- Web UI Interface & API Routes ---

@app.get("/", response_class=HTMLResponse, tags=["default"])
async def home_dashboard(db: Session = Depends(get_db)):
    active_outbreaks_count = db.query(FieldReportModel.woreda).filter(FieldReportModel.is_alert == True).distinct().count()
    total_cases_sum = db.query(func.sum(FieldReportModel.case_count)).scalar() or 0
    recent_reports = db.query(FieldReportModel).order_by(FieldReportModel.created_at.desc()).limit(10).all()
    
    table_rows_html = ""
    for r in recent_reports:
        badge = '<span class="bg-red-100 text-red-800 text-xs font-semibold px-2.5 py-0.5 rounded">CRITICAL ALERT</span>' if r.is_alert else '<span class="bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-0.5 rounded">Normal Log</span>'
        table_rows_html += f"""
        <tr class="border-b hover:bg-gray-50 text-gray-700">
            <td class="px-6 py-4 font-bold text-gray-900">{r.woreda}</td>
            <td class="px-6 py-4">{r.disease_type}</td>
            <td class="px-6 py-4 font-black">{r.case_count}</td>
            <td class="px-6 py-4">{badge}</td>
            <td class="px-6 py-4 text-xs text-gray-500">{r.created_at.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        """
    if not table_rows_html:
        table_rows_html = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-400 font-medium">No surveillance reports logged yet.</td></tr>'

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>EpiTrack Ethiopia Command Center</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://jsdelivr.net"></script>
    </head>
    <body class="bg-gray-100 font-sans">
        <nav class="bg-slate-950 p-4 text-white flex justify-between items-center shadow-md">
            <div class="flex items-center space-x-2"><span class="text-xl">🇪🇹</span><span class="font-bold text-lg tracking-wide">EpiTrack Ethiopia Dashboard</span></div>
            <div class="text-xs bg-slate-800 text-emerald-400 px-3 py-1 rounded-full border border-emerald-500/20 animate-pulse font-mono">● System Online</div>
        </nav>
        <div class="container mx-auto px-4 py-8">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div class="bg-white p-5 rounded-lg shadow-sm border border-gray-200"><div class="text-xs font-bold text-gray-400 uppercase">Active Hotspots</div><div class="text-2xl font-black text-red-600 mt-1">{active_outbreaks_count} Woredas</div></div>
                <div class="bg-white p-5 rounded-lg shadow-sm border border-gray-200"><div class="text-xs font-bold text-gray-400 uppercase">Total Cases</div><div class="text-2xl font-black text-slate-800 mt-1">{total_cases_sum} Cases</div></div>
                <div class="bg-white p-5 rounded-lg shadow-sm border border-gray-200"><div class="text-xs font-bold text-gray-400 uppercase">Lab Confirmed</div><div class="text-2xl font-black text-indigo-600 mt-1">318 Records</div></div>
                <div class="bg-white p-5 rounded-lg shadow-sm border border-gray-200"><div class="text-xs font-bold text-gray-400 uppercase">DHIS2 Sync Rate</div><div class="text-2xl font-black text-emerald-600 mt-1">98.4%</div></div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                <div class="bg-gray-50 p-4 border-b border-gray-200 flex justify-between items-center">
                    <h2 class="font-bold text-slate-800">Live Disease Intelligence Records</h2>
                    <div class="space-x-2 flex">
                        <!-- NEW FORM: Dynamic reset control button attached to interface -->
                        <form action="/api/reports/clear" method="POST" onsubmit="return confirm('Are you sure you want to clear all health logs?');">
                            <button type="submit" class="bg-red-600 text-white text-xs font-bold px-3 py-1.5 rounded hover:bg-red-700 transition shadow-sm cursor-pointer">
                                🗑 Clear All Records
                            </button>
                        </form>
                        <a href="/docs" target="_blank" class="bg-blue-600 text-white text-xs font-bold px-3 py-1.5 rounded hover:bg-blue-700 transition shadow-sm">
                            + Open Swagger API Portal
                        </a>
                    </div>
                </div>
                <table class="w-full text-left border-collapse"><thead class="bg-gray-100 text-gray-600 text-xs font-bold uppercase"><tr class="border-b"><th class="p-3 px-6">Woreda</th><th class="p-3">Disease</th><th class="p-3">Cases</th><th class="p-3">Status</th><th class="p-3 px-6">Time</th></tr></thead><tbody>{table_rows_html}</tbody></table>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/api/report", response_model=ReportResponse, status_code=status.HTTP_200_OK, tags=["default"])
async def receive_report(report: FieldReport, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    is_alert = report.disease_type.lower() == "cholera" and report.case_count >= 5
    sms_draft_en, sms_draft_om = "", ""
    if is_alert:
        alert_message = f"Outbreak Alert in {report.woreda}!"
        sms_draft_en = f"CRITICAL: {report.disease_type} outbreak detected in {report.woreda} with {report.case_count} cases."
        sms_draft_om = f"AKEEKKACHIISA HAMAAN: Dhibeen {report.disease_type} Woreda {report.woreda} keessatti namoota {report.case_count} irratti argameera."
        background_tasks.add_task(dispatch_national_telecom_alerts, report.woreda, sms_draft_om, "ethio")
    else:
        alert_message = "Report logged successfully."

    db_report = FieldReportModel(woreda=report.woreda, disease_type=report.disease_type, case_count=report.case_count, is_alert=is_alert)
    db.add(db_report)
    db.commit()

    active_outbreaks_count = db.query(FieldReportModel.woreda).filter(FieldReportModel.is_alert == True).distinct().count()
    total_cases_sum = db.query(func.sum(FieldReportModel.case_count)).scalar() or 0

    return {
        "status": "Processed Successfully", "alert": is_alert, "message": alert_message,
        "sms_draft_en": sms_draft_en, "sms_draft_om": sms_draft_om,
        "updated_dashboard": {"active_outbreaks": active_outbreaks_count, "total_suspected_cases": total_cases_sum, "lab_confirmed_cases": 318, "dhis2_transmission_rate": 98.4}
    }

# NEW ENDPOINT: Wipe the database table and redirect back home cleanly
@app.post("/api/reports/clear", tags=["default"])
async def clear_all_reports(db: Session = Depends(get_db)):
    db.query(FieldReportModel).delete()
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

