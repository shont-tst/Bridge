// Version and What's new, shown at the bottom of the home screen.
// VERSION is major.minor: the minor number goes up with every publish. The major number stays at 1 while the app is
// in early iteration and changes only when the owner says so (then the minor starts again at 1). NEWS: one entry per day,
// newest first, about the last 5 days, dated by the day it was published in Pacific time. Each entry lists the changes a player would notice in plain words, features
// first and a bare "Bug fixes." (or "Bug and UI fixes.") last (don't spell out what was fixed or small UI tweaks).
export const VERSION = "2.37";

import { CHEAT_SHEET_HTML } from "./components/CheatSheet";

export const NEWS: [string, string[]][] = [
  ["November 20, 2026", [
    "<b>Play locally:</b> games with bots now run on your phone and work with no internet. Partners on the same Wi-Fi can join by scanning a code.",
    "<b>Hints match the review:</b> when two cards make the contract about equally, the hint also shows which is likelier to take an extra trick.",
    "Bug and UI fixes.",
  ]],
  ["November 14, 2026", [
    "Bug and UI fixes.",
  ]],
  ["November 13, 2026", [
    "Security fixes.",
  ]],
  ["November 12, 2026", [
    "<b>Menu on the home screen:</b> tap ☰ on the home screen to pick the settings your new tables start with, and start any Learn & practice from there with bots.",
    "<b>Clearer review and claims:</b> the review shows what each hint was for, and when your partner claims, you see the cards.",
    "<b>Smarter bidding:</b> bots bid with vulnerability in mind from level 6, and bid better in several competitive and slam auctions.",
  ]],
  ["November 11, 2026", [
    "<b>Signals:</b> turn on Signals in the table menu, under Card play, to have defenders tell partner what they like with the size of the spot cards they play, Standard or Upside-down. The bots signal and read your signals too. Learn & practice explains attitude, count and suit preference, with practice deals where you defend.",
    "<b>Opening leads:</b> the bots now lead by Standard leads (top of a sequence, fourth best) and read your lead. Learn & practice is in the menu, under Card play.",
    "Bug fixes.",
  ]],
  ["November 10, 2026", [
    "<b>Learn to play:</b> new to bridge? Tap Learn to play on the home screen for seven short steps: tricks, trumps, minibridge, declarer play, defense, opening bids and scoring, with a tip before each card. Tell it which card games you know, such as Hearts, Spades or Euchre, and it skips what you already know.",
    "<b>Fairer review:</b> Helped or Cost on a call off the system now judges it over many deals like yours, not just this one, and close calls in hints and the review get more layouts for sharper odds.",
    "Bug fixes.",
  ]],
  ["November 7, 2026", [
    "<b>Did leaving the system pay off?</b> In the review, each call you made off the system shows whether it helped or cost you, and by how many points, compared with the system's call. My stats keeps the running total under Bidding: your average gain or loss per off-system call.",
    `<b>Cheat sheet at the table:</b> while bidding, tap Cheat sheet next to Hint to open the ${CHEAT_SHEET_HTML("No Fear Bridge cheat sheet")}.`,
    "Bug and UI fixes.",
  ]],
  ["November 6, 2026", [
    "<b>When someone leaves:</b> if a player taps Leave or is away for 3 minutes, their partner can play on with a bot in that seat, or wait. The player gets the seat back on returning.",
    "Bug fixes.",
  ]],
  ["November 3, 2026", [
    "<b>Better AI coaching:</b> your AI assistant can now look across all your boards for patterns in your leads, card play and bidding, see whether leaving the system helped or hurt, and keep notes on what you're working on.",
    "<b>Bots know the rubber score:</b> with a part score, bots at level 6 and up stop once they reach game and bid only as high as game needs; from level 8 they also compete harder to stop the other side's cheap game. Tap a bot's bid to see when the score changed it.",
    "Bug, security and UI fixes.",
  ]],
  ["October 31, 2026", [
    "<b>Bots claim too:</b> when a bot is sure to take every remaining trick, however the cards lie, it claims. You see its cards and tap Accept to end the hand, or Reject to play it out. The Claim button is now gold, so it stands out when it's yours.",
    "<b>One tap to see why:</b> tap a bot's bid or card to see why it chose it. There's no ⓘ to tap first.",
    "Bug and UI fixes.",
  ]],
  ["October 30, 2026", [
    "<b>Score first:</b> with rubber scoring, each board ends on the result and the score pad, with Review board, Next board and Quit.",
    "<b>Nobody gets rushed:</b> the next board waits until everyone at the table has tapped Next board, so someone still reading the score or the review keeps it.",
    "Bug and UI fixes.",
  ]],
  ["October 29, 2026", [
    "<b>Why did the bot do that?</b> Tap a bot's call, or a card a bot just played, then the ⓘ, to see the rule it followed or how it picked the card. Once the board is over it shows the bot's hand, its odds and the other cards it weighed, and the end-of-board panel has the auction and the play to tap through. Signed in, you can send feedback on how to improve it.",
    "<b>AI coach:</b> talk a hand through with your own AI assistant, such as Claude or ChatGPT, by text or by voice. Connect it once from your account (tap your name, then AI coach, for how), and it can read your finished boards and their review, so you can ask it why a contract went down or what to lead next time. It uses your own account with the AI company.",
    "<b>AI coaching during play:</b> your AI assistant can also see the board you're playing, just as your seat sees it, and ask the app for its hint. Everyone at the table sees AI coaching on, and the review shows how many turns you asked about, next to your hints and undos. Switch it off in the ☰ menu's table settings.",
    "<b>Your table settings stick:</b> a new table starts with the settings you last chose, such as bot strength, conventions, hints, undo, AI coaching, trick pause and scoring, kept with your account when signed in or on this phone.",
    "<b>You, top right:</b> at the table your initial now sits in the top right corner, with the score under it. Tap it for My stats, this device's settings (dealing animation, larger text, four-color suits), and your account. In the lobby, tap your name for the same. The ☰ menu now holds just the table: Skip hand, Invite to game, Change seat, Leave and the table's settings.",
    "<b>Adding friends:</b> tap + Add in your friends list for an invite link to send. Someone new makes an account with it, and someone who already plays just opens it. Either way you're friends straight away. Your friends list is now in alphabetical order.",
    "Bug and UI fixes.",
  ]],
  ["October 28, 2026", [
    "<b>Update notice:</b> when a new version of the app is out, the home screen says Update available, with a Reload button to get it. At the table a dot on your avatar at the top right shows it, with Reload at the top of its sheet, so play isn't interrupted. The Reload button is gone the rest of the time.",
    "<b>Switch devices mid-game:</b> signed in, open the app on your iPad or another phone and it goes straight to the table you were just playing at, in your seat. The device you were using shows Playing on your iPad now, with Continue here to move the game back. If you tapped Leave, the lobby has a Back to your table button instead.",
    "<b>Clearer review:</b> each card that cost a trick is now marked Mistake, when another card was the better bet with what could be seen at the time, or Unlucky, when it was as good a bet and the cards just lay badly. It shows how often each card takes the tricks your side could have had, overtricks included, and how many tricks the other side gave you.",
    "<b>End of the rubber:</b> with rubber scoring, the app tells you when you've won or lost the rubber and shows the final score pad, once you've reviewed the last board and tapped Next board. Tap Keep playing to start a new rubber, or Quit to leave the table.",
    "<b>Snappier Hint:</b> the hint for your card is worked out as soon as it's your turn, so it's usually ready the moment you tap Hint.",
    "Bug and UI fixes.",
  ]],
  ["October 27, 2026", [
    "<b>Claim:</b> when you're on lead and sure to take every remaining trick, however the other cards lie, a Claim button appears. Tap it to finish the hand with those tricks.",
    "<b>Clearer Undo:</b> the Undo button now has a bolder arrow and the word Undo.",
    "<b>Rubber scoring first:</b> new tables now start with rubber scoring. Switch to duplicate in the ☰ menu and your next table remembers it, on your account when signed in or on this phone.",
    "<b>Notices:</b> the lobby can now show a short message from the site's owner, such as a planned update. Tap ✕ to hide it.",
    "<b>Lost a phone?</b> Your account page now has Sign out other phones, which signs out every phone and tablet but the one you're holding.",
    "<b>Tidier settings:</b> table settings and your account now close with the ✕ at the top, where Invite to game, Change seat, Leave and Sign out sit too. Changes take effect as you make them.",
    "<b>Invite to game:</b> send a link to your table from the ☰ menu, even a solo practice table. A friend who joins can take your bot partner's seat.",
    "<b>Quicker tricks:</b> a finished trick now stays on the table for 2 seconds, or 1, 3 or 4 if you choose in the ☰ menu.",
    "<b>Feedback:</b> a new pull-down above Privacy for sending ideas and problems straight to the site's owner, once you're signed in.",
    `<b>New lessons:</b> takeout doubles, overcalls and raising partner's major, each with practice deals. Find them under Bidding in the ☰ menu, with a link to the ${CHEAT_SHEET_HTML("No Fear Bridge cheat sheet")} the bidding follows.`,
    `<b>Negative doubles and Jacoby 2NT:</b> two standard conventions you can switch on in the ☰ menu, each with a lesson. They're off unless you choose them, so the bidding matches the ${CHEAT_SHEET_HTML("cheat sheet")}.`,
    "<b>Hint odds:</b> a card hint now adds a second line with how often its card, and the next best one, makes (or beats) the contract, judged on what you can see.",
    "<b>Points at a glance:</b> while you bid, your points show as three numbers: high card points / with length / with shortness. Tap them for the full breakdown and what your side needs for a contract.",
    "<b>Up to four players:</b> anyone joining after the first two picks a seat, and the bots play any empty seat. Or choose Just watch to follow a table with all four hands showing.",
    "<b>Accounts and friends:</b> sign in with Face ID, add friends, and tap Play to send them an invite, with a notification on their phone.",
    "<b>My stats:</b> your results, your level on the bots' 1 to 10 scale, and every hand you've played.",
    "<b>Games survive updates:</b> a new version no longer ends the table.",
    "Bug fixes.",
  ]],
  ["October 26, 2026", [
    "<b>Easier-to-read cards</b> and a quieter table, with dummy in a row on iPhone and in columns on iPad.",
    "<b>Following partner's contract:</b> when partner declares, you see their hand as well as your own.",
    "<b>Undo:</b> take back calls and cards, back to the start of the board.",
    "<b>Rubber scoring</b> as a choice in Settings, alongside duplicate.",
  ]],
  ["October 25, 2026", [
    "<b>New look:</b> a new name and a card-table look.",
    "<b>Learning tools:</b> a review after each board, hints, and practice deals for each convention.",
    `<b>First version:</b> play with a partner against bots, with the ${CHEAT_SHEET_HTML("No Fear Bridge")} bidding system.`,
  ]],
];
