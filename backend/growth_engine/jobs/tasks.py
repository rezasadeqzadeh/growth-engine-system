"""Every background job kind and its handler."""

from .. import db
from ..i18n import t
from ..models import Post
from ..services import (
    approval, audit, calendar, caption_jobs, competitors, feedback, maintenance, metrics, pipeline, publishing,
    reports,
)
from . import queue
from .runner import handler


def _post_failed(payload: dict, message: str) -> None:
    with db.session_scope() as s:
        post = s.get(Post, payload["post_id"])
        if post is None:
            return
        post.status, post.error = "failed", message[:500]
        queue.enqueue(s, "notify_text", {"workspace_id": post.workspace_id, "key": "bot.processing_failed",
                                   "values": {"title": post.title or t("post.untitled")}})


handler("process_video", on_final_failure=_post_failed)(pipeline.process_video)
handler("send_approval_card")(approval.send_approval_card)
handler("send_handoff")(approval.send_handoff)
handler("send_srt")(approval.send_srt)
handler("edit_captions")(caption_jobs.edit_captions)
handler("transcribe_voice")(caption_jobs.transcribe_voice)
handler("publish_variant", on_final_failure=publishing.on_publish_failed)(publishing.publish_variant)
handler("publish_reminder")(publishing.publish_reminder)
handler("notify_text")(publishing.notify_text)
handler("collect_metrics")(metrics.collect_metrics)
handler("collect_comments")(metrics.collect_comments)
handler("read_insights")(metrics.read_insights)
handler("classify_feedback")(feedback.classify_pending)
handler("send_content_requests")(calendar.send_content_requests)
handler("generate_calendar")(maintenance.generate_next_month)
handler("run_audit", on_final_failure=audit.on_failed)(audit.run)
handler("analyze_competitors")(competitors.analyze)
handler("weekly_report")(reports.weekly_report)
handler("auto_approve")(maintenance.auto_approve)
handler("channel_health")(maintenance.channel_health)
handler("refresh_instagram_tokens")(maintenance.refresh_instagram_tokens)
handler("learn_best_hour")(maintenance.learn_best_hour)
