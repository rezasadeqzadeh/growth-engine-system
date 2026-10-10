// Shapes of the backend's JSON (growth_engine/api/*).

export type Role = "owner" | "operator" | "approver" | "sender";

export interface Workspace {
  id: string; name: string; slug: string; vertical: string; plan: string; agency_id: string | null;
  role: Role | null; settings: Record<string, unknown>;
  brand: { display_name: string; primary_color: string };
  usage?: Record<string, { used: number; limit: number }>;
}

export interface QcItem { check: string; level: "ok" | "warn" | "fail"; message: string; params: Record<string, string | number> }

export interface PostSummary {
  id: string; title: string; tag: string | null; tag_guessed: boolean; status: string; scheduled_at: string | null;
  created_at: string; qc: QcItem[]; duration_s: number | null; auto_approve_at: string | null; rating: number | null;
}

export interface Variant {
  id: string; channel: { id: string; type: string; name: string }; kind: string; title: string; caption: string;
  tags: string[]; video_url: string | null; cover_url: string | null; srt_url: string | null; tracked_link: string | null;
  publications: { status: string; url: string | null; error: string | null; at: string | null }[];
}

export interface SubtitleLine { start: number; end: number; text: string }

export interface PostDetail extends PostSummary {
  raw_note: string; variants: Variant[]; subtitles: string | null; subtitle_lines: SubtitleLine[]; faces: number;
}

export interface Recipe {
  id?: string; tag: string; goal: string; pillar: string | null; caption_style: string; cta: string;
  video_spec: { min_s?: number; max_s?: number; aspects?: string[]; subtitle_mode?: string; overlay?: string; music?: boolean };
  channels: string[]; timing: { mode: string; hour?: number; reminder_days?: number }; low_risk: boolean;
}

export interface ChannelOut {
  id: string; type: string; name: string; config: Record<string, string>; enabled: boolean; secrets_set: string[];
  health_ok: boolean | null; health_error: string | null; health_checked_at: string | null;
  capabilities: { auto_publish: boolean; metrics: string; comments: string; max_video_mb: number };
}

export interface Slot {
  id: string; day: string; kind: string; pillar: string | null; goal: string | null; tag: string | null; title: string;
  note: string; occasion: string | null; post_id: string | null; needs_media: boolean; requested: boolean;
}
