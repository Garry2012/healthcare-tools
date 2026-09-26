"""Outbound notification queue for impacted customers (tag `Notifications`)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from .. import schemas as s
from ..auth import require_scopes
from ..services import notifications as svc
from .deps import ActingUser, ApiDate, Session, SettingsDep, errors, respond

router = APIRouter(tags=["Notifications"], dependencies=[Depends(require_scopes("bookings.staff"))])


@router.get("/notifications", operation_id="listNotifications",
            summary="Pending and sent notifications to impacted customers",
            response_model=s.NotificationList, responses=errors(403))
async def list_notifications(
    session: Session,
    status: Literal["PENDING", "SENT", "FAILED", "ACKNOWLEDGED"] = "PENDING",
    resource_id: Annotated[str | None, Query(alias="resourceId")] = None,
    on: Annotated[ApiDate | None, Query(alias="date")] = None,
):
    return respond(await svc.list_notifications(session, status=status, resource_id=resource_id, on=on))


@router.post("/notifications/{notificationId}/delivered", operation_id="markNotificationDelivered",
             summary="Record that the customer was informed (by desk today, by SMS/voice bot later)",
             response_model=s.Notification, responses=errors(403, 404))
async def mark_notification_delivered(
    notificationId: str, body: s.DeliveredRequest, acting_user: ActingUser,  # noqa: N803
    session: Session, settings: SettingsDep,
):
    return respond(await svc.mark_delivered(session, settings, notificationId, body, f"staff:{acting_user}"))
