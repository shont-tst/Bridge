import { NEWS, VERSION } from "../version";

/** "Version 1.7 · What's new": opens the dated list of changes, newest first. Reload is in UpdateBanner, shown only
 * when a newer version is out. */
export default function WhatsNew() {
  return (
    <details className="whats-new">
      <summary>Version {VERSION} · What's new</summary>
      {NEWS.map(([day, items]) => (
        <section key={day}>
          <h3>{day}</h3>
          <ul>
            {items.map((item, i) => (
              <li key={i} dangerouslySetInnerHTML={{ __html: item }} />
            ))}
          </ul>
        </section>
      ))}
    </details>
  );
}
