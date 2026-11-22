import { useState } from "react";
import { reloadLatest, useUpdate } from "../update";

/** "Update available": shown only when a newer version is published than the one running, with a Reload button. */
export default function UpdateBanner({ compact = false }: { compact?: boolean }) {
  const latest = useUpdate();
  const [reloading, setReloading] = useState(false);
  if (!latest) return null;
  return (
    <div className={compact ? "update-banner compact" : "update-banner"} role="status">
      <span>
        <strong>Update available</strong>
        <br />
        Version {latest} is out.
      </span>
      <button
        className="chip gold"
        disabled={reloading}
        onClick={() => {
          setReloading(true);
          reloadLatest();
        }}
      >
        {reloading ? "Reloading…" : "Reload"}
      </button>
    </div>
  );
}
