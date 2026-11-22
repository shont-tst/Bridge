/** This site's name (BRIDGE_APP_NAME on the server, plain "Bridge" when unset). The server writes it into the page's
 * Home Screen name (index.html), so the app reads it from there, also when it opens from the phone's copy. */
export const APP_NAME =
  document.querySelector<HTMLMetaElement>('meta[name="apple-mobile-web-app-title"]')?.content.trim() || "Bridge";
