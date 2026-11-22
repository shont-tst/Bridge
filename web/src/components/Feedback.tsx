import { useState } from "react";
import { api, loadToken } from "../account";
import { VERSION } from "../version";

/** The Feedback pull-down: a suggestion box. Suggestions go to the site's owner to read. Only for signed-in players:
 * guests don't see it, and the server refuses theirs.
 *
 * At the table it is about something: `about` is sent along ({bid: {room, board, index}} for a bot's call, or
 * {board: {room, board}} for the board, from the Feedback link on the score strip), and the server adds the deal, auction and play itself, so
 * the note can be short, or empty for a call. */
export default function Feedback({ about, intro, placeholder, optional, bare }: {
  about?: Record<string, unknown>;
  bare?: boolean; // in a sheet of its own: the form itself, not a pull-down
  intro?: string;
  placeholder?: string;
  optional?: boolean; // a note isn't needed: what it's about says enough
}) {
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [err, setErr] = useState<string | null>(null);
  const send = async () => {
    setState("sending");
    setErr(null);
    try {
      await api("/api/feedback", { text, version: VERSION, ...about }, loadToken());
      setText("");
      setState("sent");
    } catch (e) {
      setErr((e as Error).message);
      setState("idle");
    }
  };
  if (!loadToken()) return null;
  const form = (
    <>
      <p>{intro ?? "Ideas, problems, anything you'd change? The site's owner reads every one."}</p>
      <textarea
        value={text}
        maxLength={2000}
        rows={optional ? 3 : 4}
        placeholder={placeholder ?? "Your suggestion"}
        onChange={(e) => {
          setText(e.target.value);
          if (state === "sent") setState("idle");
        }}
      />
      <div className="reload">
        <button className="chip" disabled={(!optional && !text.trim()) || state === "sending" || state === "sent"} onClick={send}>
          {state === "sending" ? "Sending…" : "Send"}
        </button>
        {state === "sent" && <span>Thanks! It's been sent.</span>}
        {err && <span className="error">{err}</span>}
      </div>
    </>
  );
  return bare ? (
    <div className="whats-new feedback">{form}</div>
  ) : (
    <details className="whats-new feedback">
      <summary>Feedback</summary>
      {form}
    </details>
  );
}
