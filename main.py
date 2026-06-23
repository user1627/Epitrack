from typing import List, Optional
from fastapi import FastAPI, Depends, status, Query, BackgroundTasks, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import jwt
import bcrypt
import requests
import csv
import os
from io import StringIO

from database import engine, Base, get_db
from models import FieldReportModel

Base.metadata.create_all(bind=engine)
app = FastAPI(title="EpiTrack Ethiopia", version="6.5.0")

SECRET_KEY = "ethio_national_surveillance_ultra_secret_key_2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

USER_DB = {
    "officer_jimma": {"hashed_password": hash_password("EthioOfficer2026"), "role": "field_officer"},
    "admin_command": {"hashed_password": hash_password("SurveillanceDirector100"), "role": "admin"}
}

class Token(BaseModel):
    access_token: str
    token_type: str

class FieldReport(BaseModel):
    woreda: str = Field(..., min_length=2, max_length=50)
    disease_type: str = Field(..., min_length=3, max_length=50)
    case_count: int = Field(..., ge=0, le=100000)

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

def get_user_role_from_token(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("role")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token credentials")

@app.post("/api/token", response_model=Token, tags=["Authentication"])
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = USER_DB.get(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode({"sub": form_data.username, "role": user["role"], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/v1/dashboard-data", tags=["Data Engine"])
async def get_dashboard_telemetry_data(db: Session = Depends(get_db)):
    active_outbreaks = db.query(FieldReportModel.woreda).filter(FieldReportModel.is_alert == True).distinct().count()
    total_cases = db.query(func.sum(FieldReportModel.case_count)).scalar() or 0
    recent_reports = db.query(FieldReportModel).order_by(FieldReportModel.created_at.desc()).limit(10).all()
    
    chart_query = db.query(FieldReportModel.woreda, func.sum(FieldReportModel.case_count)).group_by(FieldReportModel.woreda).all()
    chart_labels = [str(row[0]) for row in chart_query]
    chart_values = [int(row[1]) for row in chart_query]
    
    rows_html = ""
    for r in recent_reports:
        badge = "BALAA / CRITICAL" if r.is_alert else "NAGAA / Normal"
        style = "background:#fee2e2; color:#991b1b;" if r.is_alert else "background:#dcfce7; color:#166534;"
        rows_html += f'<tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:12px; font-weight:bold;">{r.woreda}</td><td style="padding:12px;">{r.disease_type}</td><td style="padding:12px; font-weight:900;">{r.case_count}</td><td style="padding:12px;"><span style="{style} font-size:11px; font-weight:bold; padding:2px 8px; border-radius:4px;">{badge}</span></td><td style="padding:12px; font-size:12px; color:#64748b;">{r.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>'
    
    if not rows_html:
        rows_html = '<tr><td colspan="5" style="padding:24px; text-align:center; color:#94a3b8;">Gabaasni hin jiru.</td></tr>'
        
    return {
        "active_outbreaks": active_outbreaks,
        "total_cases": total_cases,
        "rows_html": rows_html,
        "chart_labels": chart_labels,
        "chart_values": chart_values
    }

@app.get("/", response_class=HTMLResponse, tags=["Dashboard UI"])
async def home_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), "dashboard.html") if "__file__" in locals() else "dashboard.html"
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/ui/report/submit", tags=["Dashboard UI Actions"])
async def submit_report_from_ui(background_tasks: BackgroundTasks, woreda: str = Form(...), disease_type: str = Form(...), case_count: int = Form(...), db: Session = Depends(get_db)):
    new_report = FieldReportModel(woreda=woreda, disease_type=disease_type, case_count=case_count, is_alert=(case_count >= 10), created_at=datetime.utcnow())
    db.add(new_report)
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/api/reports/export", tags=["Data Analysis & Export"])
async def export_reports_to_csv(db: Session = Depends(get_db)):
    reports = db.query(FieldReportModel).order_by(FieldReportModel.created_at.desc()).all()
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(["ID", "Woreda", "Disease Pathology", "Cases", "Status", "Timestamp"])
    for r in reports:
        writer.writerow([r.id, r.woreda, r.disease_type, r.case_count, ("BALAA / CRITICAL" if r.is_alert else "NAGAA / Normal"), r.created_at.strftime('%Y-%m-%d %H:%M')])
    stream.seek(0)
    response = StreamingResponse(stream, media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=EpiTrack_Report_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return response

@app.post("/api/reports", response_model=ReportResponse, status_code=status.HTTP_201_CREATED, tags=["Secure API Endpoints"])
async def create_api_report(report: FieldReport, background_tasks: BackgroundTasks, db: Session = Depends(get_db), role: str = Depends(get_user_role_from_token)):
    is_alert = report.case_count >= 10
    new_report = FieldReportModel(woreda=report.woreda, disease_type=report.disease_type, case_count=report.case_count, is_alert=is_alert, created_at=datetime.utcnow())
    db.add(new_report)
    db.commit()
    active_outbreaks = db.query(FieldReportModel.woreda).filter(FieldReportModel.is_alert == True).distinct().count()
    total_cases = db.query(func.sum(FieldReportModel.case_count)).scalar() or 0
    return ReportResponse(
        status="Success",
        alert=is_alert,
        message="Processed under secure JWT scope.",
        sms_draft_en=f"CRITICAL: Outbreak of {report.disease_type} in {report.woreda} woreda.",
        sms_draft_om=f"SUDDOO: {report.woreda} keessatti dhukkubni {report.disease_type} gabaafameera.",
        updated_dashboard=DashboardMetrics(active_outbreaks=active_outbreaks, total_suspected_cases=total_cases, lab_confirmed_cases=318, dhis2_transmission_rate=98.4)
    )
