import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** A small ⓘ button that opens a pop-up explaining how something is worked out. The pop-up goes on the page body,
 * so it sits above any sheet and a tap inside it never reaches a label or checkbox around the button.
 * With `onClose`, there's no button: the pop-up is open until closed (the end-of-board Auction and Play open it on a tap). */
export default function Info({ title, heading, children, onClose }: { title: string; heading?: ReactNode; children: ReactNode; onClose?: () => void }) {
  const [shown, setOpen] = useState(false);
  const open = onClose ? true : shown;
  const close = onClose ?? (() => setOpen(false));
  return (
    <>
      {!onClose && <button
        type="button"
        className="info-button"
        aria-label={`How it works: ${title}`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen(true);
        }}
      >
        {/* drawn, not a font glyph: ⓘ comes out as a hairline on iPhone */}
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="8.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <circle cx="10" cy="6" r="1.3" fill="currentColor" />
          <rect x="8.9" y="8.6" width="2.2" height="6.4" rx="1.1" fill="currentColor" />
        </svg>
      </button>}
      {open &&
        createPortal(
          <div className="sheet-backdrop info-backdrop" onClick={close}>
            <div className="sheet info-sheet" onClick={(e) => e.stopPropagation()}>
              <div className="sheet-top">
                <h2>{heading ?? title}</h2>
                <button className="close" onClick={close} aria-label="Close">
                  ✕
                </button>
              </div>
              {children}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
