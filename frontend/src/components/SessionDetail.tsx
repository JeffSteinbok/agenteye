/**
 * Session detail panel — shown when a session card is expanded (list view)
 * or when a tile is clicked (modal view).
 *
 * Fetches /api/session/:id and renders checkpoints, refs, recent output,
 * conversation turns, and tool usage bars.
 */

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchSessionDetail, fetchSessionPlan } from "../api";
import type { SessionDetail as SessionDetailType, SessionPlan } from "../types";

interface SessionDetailProps {
  sessionId: string;
}

export default function SessionDetail({ sessionId }: SessionDetailProps) {
  const [data, setData] = useState<SessionDetailType | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    fetchSessionDetail(sessionId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (error) return <div className="empty">Error loading details.</div>;
  if (!data) return <div className="loading">Loading...</div>;

  const hasContent =
    data.checkpoints.length > 0 ||
    data.refs.length > 0 ||
    data.recent_output.length > 0 ||
    data.turns.length > 0 ||
    data.tool_counts.length > 0;

  return (
    <>
      <PlanSection sessionId={sessionId} />
      {!hasContent && <div className="empty">No additional details for this session.</div>}
      <CheckpointsSection checkpoints={data.checkpoints} sessionId={sessionId} />
      <RefsSection refs={data.refs} />
      <RecentOutputSection lines={data.recent_output} />
      <TurnsSection turns={data.turns} />
      <ToolCountsSection toolCounts={data.tool_counts} />
    </>
  );
}

function PlanSection({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SessionPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const loadPlan = useCallback(() => {
    setLoading(true);
    setError(false);
    fetchSessionPlan(sessionId)
      .then((plan) => setData(plan))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const progress =
    data?.progress ? ` (${data.progress.done}/${data.progress.total} done)` : "";

  const toggleOpen = () => {
    if (!open) loadPlan();
    setOpen(!open);
  };

  return (
    <div className="detail-section">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <h3 style={{ marginBottom: 0 }}>📝 Plan{progress}</h3>
        <div style={{ display: "flex", gap: 8 }}>
          {open && (
            <button className="copy-btn" onClick={loadPlan}>
              Refresh
            </button>
          )}
          <button className="copy-btn" onClick={toggleOpen}>
            {open ? "Hide" : "Show"}
          </button>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
          {loading && <div className="loading">Loading plan...</div>}
          {!loading && error && <div className="empty">Error loading plan.</div>}
          {!loading && !error && !data?.content && <div className="empty">No plan file.</div>}
          {!loading && !error && data?.content && (
            <>
              <div style={{ color: "var(--text2)", fontSize: 12, marginBottom: 10 }}>
                <div>{data.path}</div>
                {data.mtime && <div>Updated {new Date(data.mtime).toLocaleString()}</div>}
              </div>
              <div
                style={{
                  background: "var(--surface2)",
                  borderRadius: 6,
                  padding: 12,
                  overflowX: "auto",
                }}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code(props) {
                      const { children, className, ...rest } = props;
                      return (
                        <code
                          className={className}
                          style={{
                            background: "rgba(255,255,255,0.08)",
                            borderRadius: 4,
                            padding: "0.1em 0.3em",
                            fontFamily: "'Cascadia Code','Fira Code',monospace",
                          }}
                          {...rest}
                        >
                          {children}
                        </code>
                      );
                    },
                    pre(props) {
                      return (
                        <pre
                          style={{
                            background: "rgba(0,0,0,0.2)",
                            borderRadius: 6,
                            padding: 12,
                            overflowX: "auto",
                            whiteSpace: "pre-wrap",
                          }}
                          {...props}
                        />
                      );
                    },
                  }}
                >
                  {data.content}
                </ReactMarkdown>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Sub-sections — each renders one block of the detail panel ────────────────

function CheckpointsSection({
  checkpoints,
  sessionId,
}: {
  checkpoints: SessionDetailType["checkpoints"];
  sessionId: string;
}) {
  if (checkpoints.length === 0) return null;

  return (
    <div className="detail-section">
      <h3>🏁 Checkpoints</h3>
      {checkpoints.map((cp, i) => (
        <CheckpointItem key={i} cp={cp} id={`cp-${sessionId}-${i}`} />
      ))}
    </div>
  );
}

function CheckpointItem({
  cp,
  id,
}: {
  cp: SessionDetailType["checkpoints"][number];
  id: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="cp-item" onClick={() => setOpen(!open)}>
      <strong>
        #{cp.checkpoint_number}: {cp.title || "Checkpoint"}
      </strong>
      {open && (
        <div id={id}>
          {cp.overview && <div className="cp-body">{cp.overview}</div>}
          {cp.next_steps && (
            <div className="cp-body" style={{ marginTop: 4, color: "var(--yellow)" }}>
              <strong>Next:</strong> {cp.next_steps}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RefsSection({ refs }: { refs: SessionDetailType["refs"] }) {
  if (refs.length === 0) return null;

  return (
    <div className="detail-section">
      <h3>🔗 References</h3>
      <div className="file-list">
        {refs.map((r, i) => (
          <span key={i} className="ref-tag">
            {r.ref_type}: {r.ref_value}
          </span>
        ))}
      </div>
    </div>
  );
}

function RecentOutputSection({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;

  return (
    <div className="detail-section">
      <h3>📟 Recent Output</h3>
      <pre
        style={{
          background: "var(--surface2)",
          borderRadius: 6,
          padding: 12,
          fontSize: 13,
          fontFamily: "'Cascadia Code','Fira Code',monospace",
          color: "var(--text2)",
          overflowX: "auto",
          whiteSpace: "pre-wrap",
          maxHeight: 300,
          overflowY: "auto",
        }}
      >
        {lines.map((line, i) => (
          <span key={i}>
            {line}
            {"\n"}
          </span>
        ))}
      </pre>
    </div>
  );
}

function TurnsSection({ turns }: { turns: SessionDetailType["turns"] }) {
  if (turns.length === 0) return null;

  return (
    <div className="detail-section">
      <h3>💬 Conversation (last 10)</h3>
      {[...turns].reverse().map((t, i) => {
        const u = (t.user_message || "").substring(0, 250);
        const a = (t.assistant_response || "").substring(0, 250);
        return (
          <div key={i} className="turn-item">
            {u && (
              <div className="turn-user">
                👤 {u}
                {t.user_message && t.user_message.length > 250 ? "..." : ""}
              </div>
            )}
            {a && (
              <div className="turn-assistant">
                🤖 {a}
                {t.assistant_response && t.assistant_response.length > 250 ? "..." : ""}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ToolCountsSection({
  toolCounts,
}: {
  toolCounts: SessionDetailType["tool_counts"];
}) {
  if (toolCounts.length === 0) return null;

  const maxCount = toolCounts[0].count;

  return (
    <div className="detail-section">
      <h3>🔧 Tools used</h3>
      {toolCounts.map((t) => {
        const pct = Math.round((t.count / maxCount) * 100);
        return (
          <div
            key={t.name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 4,
              fontSize: 13,
            }}
          >
            <span
              style={{
                minWidth: 160,
                fontFamily: "monospace",
                color: "var(--text2)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {t.name}
            </span>
            <div
              style={{
                flex: 1,
                height: 8,
                background: "var(--surface2)",
                borderRadius: 4,
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: "var(--accent)",
                  borderRadius: 4,
                }}
              />
            </div>
            <span
              style={{ minWidth: 30, textAlign: "right", color: "var(--text)" }}
            >
              {t.count}
            </span>
          </div>
        );
      })}
    </div>
  );
}
