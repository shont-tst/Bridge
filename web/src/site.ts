/** This site's name (BRIDGE_APP_NAME on the server, plain "Bridge" when unset). The server writes it into the page's
 * Home Screen name (index.html), so the app reads it from there, also when it opens from the phone's copy. */
export const APP_NAME =
  document.querySelector<HTMLMetaElement>('meta[name="apple-mobile-web-app-title"]')?.content.trim() || "Bridge";

/** Where this app's open source code is (BRIDGE_SOURCE_URL on the server, written into index.html like the name), or
 * "" when the site doesn't say. What's new links to it. */
export const SOURCE_URL = (() => {
  const u = document.querySelector<HTMLMetaElement>('meta[name="source-url"]')?.content.trim() ?? "";
  return u.startsWith("https://") ? u : "";
})();
