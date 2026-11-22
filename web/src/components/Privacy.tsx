/** The Privacy pull-down, under What's new on the home screen and in Settings. */
const PRIVACY = [
  "<b>On this phone:</b> your settings, the name you play under, the table you're at, your Learn to play progress and, when signed in, a sign-in key are kept in this browser, with a random number that tells your devices apart, so a game can follow you from one to another. They aren't sent anywhere except to play.",
  "<b>Face ID:</b> your face or fingerprint never leaves your phone. The phone keeps a passkey for this site and only proves to the server that it's you. There's no password, and no email address or phone number is asked for.",
  "<b>Your account</b> keeps your name, your friend code, your friends, and each board you finish while signed in: the hands, the bidding and play, the score, and the hints and undos you used, plus the card games you told Learn to play you know and the steps you've finished. Your stats and hand history are seen only by you and the site's owner. Friends see your name and whether you're ready to play, at a table or away, and when you were last in the app. While you're at a table, friends can join it or watch, and so can anyone with its room code. People watching see what the players see, and all four hands once each board ends.",
  "<b>Notifications</b> are only for invites from friends and the odd notice from the site's owner, and only if you turn them on. Turn them off at any time in your account.",
  "<b>Playing without signing in:</b> a table is kept on the server for up to two days so you can reconnect, and isn't linked to you.",
  "<b>Feedback:</b> a suggestion you send is kept with your name and the app's version, and is read only by the site's owner (and the AI assistant that helps build the app).",
  "<b>AI coach:</b> if you connect your own AI assistant (such as Claude or ChatGPT) in your account, it can read your finished boards, their review and your stats whenever you ask it about them, and, at tables that allow AI coaching during play, the board you're playing as your seat sees it. It can also keep short notes in your account on what you're working on, which go when you delete your account. What it reads goes to that AI company under your own account with them and their privacy terms. Nothing is shared until you tap Allow, and you can remove it in your account at any time.",
  "<b>Data retention:</b> bridge data is kept in its own storage, separate from the site owner's other apps, with a weekly backup there that's kept for 12 weeks. There are no ads or outside tracking services.",
  "<b>To reset:</b> sign out in your account, or clear this site's data in your browser settings. To remove your account and saved boards, ask the site's owner (copies in the weekly backups go as those backups age out). Accounts not used for 12 months may be removed.",
];

export default function Privacy() {
  return (
    <details className="whats-new privacy">
      <summary>Privacy</summary>
      {PRIVACY.map((p, i) => (
        <p key={i} dangerouslySetInnerHTML={{ __html: p }} />
      ))}
    </details>
  );
}
