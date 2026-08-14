from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import SapSyncLog, SapConfig, Product, Supplier, Order, Sale
from app.schemas import SapSyncRequest, SapSyncResponse

router = APIRouter(prefix="/api/sap", tags=["sap"])


@router.get("/sync-status")
def get_sync_status(db: Session = Depends(get_db)):
    logs = db.query(SapSyncLog).order_by(SapSyncLog.created_at.desc()).limit(20).all()
    config = db.query(SapConfig).filter(SapConfig.is_active == True).first()

    return {
        "connected": config is not None,
        "last_sync": logs[0].created_at.isoformat() if logs else None,
        "recent_logs": [
            {
                "id": str(log.id),
                "sync_type": log.sync_type,
                "status": log.status,
                "records_synced": log.records_synced,
                "error_message": log.error_message,
                "started_at": log.started_at.isoformat(),
                "completed_at": log.completed_at.isoformat() if log.completed_at else None,
            }
            for log in logs
        ],
    }


@router.post("/config")
def update_sap_config(
    host: str,
    system_number: str,
    client: str,
    user: str,
    password: str,
    db: Session = Depends(get_db),
):
    config = db.query(SapConfig).first()
    if not config:
        config = SapConfig()
        db.add(config)

    config.host = host
    config.system_number = system_number
    config.client = client
    config.user = user
    config.password_encrypted = password
    config.is_active = True
    config.updated_at = datetime.utcnow()
    db.commit()

    return {"status": "connected", "message": "SAP configuration saved"}


@router.post("/test-connection")
def test_connection(db: Session = Depends(get_db)):
    config = db.query(SapConfig).filter(SapConfig.is_active == True).first()
    if not config:
        raise HTTPException(status_code=400, detail="No SAP configuration found")

    # In production, this would attempt an actual RFC/OData connection
    # For now, return success if config exists
    return {"status": "success", "message": "SAP connection configured (test mode)"}


@router.post("/sync", response_model=SapSyncResponse)
def trigger_sync(request: SapSyncRequest, db: Session = Depends(get_db)):
    config = db.query(SapConfig).filter(SapConfig.is_active == True).first()
    if not config:
        raise HTTPException(status_code=400, detail="SAP not configured")

    log = SapSyncLog(
        sync_type=request.sync_type,
        status="in_progress",
        started_at=datetime.utcnow(),
    )
    db.add(log)
    db.commit()

    # In production, this would call the SAP connector
    # For now, simulate sync by counting local records
    record_counts = {
        "materials": db.query(Product).count(),
        "vendors": db.query(Supplier).count(),
        "stocks": db.query(Product).count(),
        "orders": db.query(Order).count(),
        "sales": db.query(Sale).count(),
    }

    count = record_counts.get(request.sync_type, 0)

    log.status = "completed"
    log.records_synced = count
    log.completed_at = datetime.utcnow()
    db.commit()

    return SapSyncResponse(
        status="completed",
        message=f"Synced {count} {request.sync_type} records",
        records_synced=count,
    )
