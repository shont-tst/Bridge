/** The No Fear Bridge cheat sheet the bidding follows. Every mention of it in the app is a link that opens it. */
export const CHEAT_SHEET = "https://www.nofearbridge.com/bridge_bidding_cheat_sheet.pdf";

/** The same link as HTML, for text written as HTML (What's new). */
export const CHEAT_SHEET_HTML = (text: string) => `<a href="${CHEAT_SHEET}" target="_blank" rel="noopener noreferrer">${text}</a>`;

export default function CheatSheetLink({ children = "No Fear Bridge cheat sheet" }: { children?: React.ReactNode }) {
  return (
    <a href={CHEAT_SHEET} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
