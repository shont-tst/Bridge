import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { SEAT_NAME, SUIT_SYMBOL, callLabel, cardLabel, compass, isRed, partnerOf, sameSide, signed } from "../cards";
import { loadToken, type Account, type FriendsView } from "../account";
import { REMEMBERED, reducedMotion, usePrefs } from "../prefs";
import type { Hint, ReplaySpec, RoomState, Seat, Settings, TableState } from "../types";
import { replaySpec } from "../replay";
import PuzzleSheet from "./PuzzleSheet";
import { useUpdate } from "../update";
import AuctionView from "./AuctionView";
import BiddingBox from "./BiddingBox";
import BidWhy from "./BidWhy";
import BidTiles from "./BidTiles";
import DealAnimation from "./DealAnimation";
import CardWhy from "./CardWhy";
import Dummy from "./Dummy";
import { useDummyFit } from "./useDummyFit";
import { HintsInfo } from "./Explain";
import Fan from "./Fan";
import Feedback from "./Feedback";
import InviteSheet from "./InviteSheet";
import { deviceName, type Queued } from "../connection";
import PlayView from "./PlayView";
import PointsPanel from "./PointsPanel";
import BoardScore from "./BoardScore";
import ResultPanel from "./ResultPanel";
import RubberOver from "./RubberOver";
import GoneSheet from "./GoneSheet";
import SkipSheet from "./SkipSheet";
import ScoreSheet from "./ScoreSheet";
import SeatPicker from "./SeatPicker";
import { CHEAT_SHEET } from "./CheatSheet";
import SettingsPanel from "./SettingsPanel";
import SuitText from "./SuitText";
import UndoIcon from "./UndoIcon";
import TrickArea from "./TrickArea";

const WifiInvite = lazy(() => import("./WifiPair").then((m) => ({ default: m.WifiInvite }))); // its QR reader is large
import { TutorialTable, callCheck } from "./TutorialTable";
import { APP_NAME } from "../site";

interface Props {
  state: RoomState | null;
  hint: Hint | null;
  hintPending: boolean;
  askHint: () => void;
  error: string | null;
  connected: boolean;
  unreachable?: boolean; // no internet, and this device has no copy of the table to go on with
  queued?: Queued | null; // a call or card still on its way to the table (connection.ts)
  send: (msg: object) => void;
  onLeave: () => void;
  onQuit?: () => void; // leave for good (Leave, then Quit table)
  onTutorialStop?: () => void; // a Learn to play table: Stop goes back to the course
  onYou: (focus?: "ai") => void; // the avatar at the top right: you, this device's settings, and your account when signed in
  initial?: string; // your name's first letter when signed in; a guest gets a plain person icon
  account?: Account; // signed in: Invite to game lists your friends
  friends?: FriendsView | null;
  inviting?: boolean; // the lobby's Invite for a friend with notifications off: open Invite to game to send a link
  coachOff?: boolean; // a table the AI coach can't see now (on this phone with no internet, or not signed in)
  onLocalInvite?: () => Promise<boolean>; // Invite at a bot table on this phone: true once it moved to the server
  // the table is on this phone, or on a partner's phone over the Wi-Fi (offline.ts, wifi.ts), or a bot table of this
  // phone's kept on the server for an invite (App.tsx)
  where?: "local" | "wifi" | "invite";
  onReplay?: (spec: ReplaySpec) => void; // Play on from here, or Play this deal again, from the review at a table
  onDone?: () => void; // a deal played again, or Your mistakes: back to where you came from
  onSeeBoard?: (key: string) => void; // Your mistakes: the saved board a puzzle comes from
}


const PersonIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <circle cx="12" cy="8.5" r="4" fill="currentColor" />
    <path d="M4 20.5c0-4.2 3.6-6.5 8-6.5s8 2.3 8 6.5" fill="currentColor" />
  </svg>
);
type Where = "top" | "left" | "right" | "bottom";

function useMedia(q: string) {
  const [on, setOn] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const change = () => setOn(m.matches);
    m.addEventListener("change", change);
    return () => m.removeEventListener("change", change);
  }, [q]);
  return on;
}

export const SIZES = {
  phone: { hand: [64, 90], back: [26, 38], dummy: [52, 74], sideDummy: [44, 62] },
  wide: { hand: [100, 140], back: [40, 58], dummy: [80, 112], sideDummy: [76, 106] },
  // iPad held sideways: less height, so dummy's columns are a little smaller
  wideShort: { hand: [96, 134], back: [40, 58], dummy: [68, 96], sideDummy: [60, 84] },
  // a laptop window: wide but low, so the hand and bidding box shrink to leave the table room
  wideLow: { hand: [80, 112], back: [32, 46], dummy: [60, 84], sideDummy: [52, 74] },
  wideLower: { hand: [72, 100], back: [32, 46], dummy: [56, 78], sideDummy: [50, 70] },
};
const CLAIM_TRICK = 1000; // ms a finished trick of a claim is on show (CLAIM_TRICK in the server's game/room.py)

export const HAND_SPREAD = 12; // degrees: only a slight fan, so every card stands nearly upright

function dealtBefore(key: string): boolean {
  try {
    if (sessionStorage.getItem("bridge-dealt") === key) return true;
    sessionStorage.setItem("bridge-dealt", key);
  } catch {
    /* private mode: animate anyway */
  }
  return false;
}

/** The table as it will be once `seat` has played `card`. */
function playedAhead(t: TableState, seat: Seat, card: string): TableState {
  const fresh = !t.trick || t.trick.cards.length === 4;
  const trick = fresh ? { leader: seat, cards: [{ seat, card }] } : { ...t.trick!, cards: [...t.trick!.cards, { seat, card }] };
  return {
    ...t,
    trick,
    your_turn: false,
    legal_cards: [],
    turn: null,
    hands: { ...t.hands, [seat]: t.hands[seat]?.filter((c) => c !== card) ?? null },
    counts: { ...t.counts, [seat]: Math.max(0, t.counts[seat] - 1) },
  };
}

export default function TableView({ state, hint, hintPending, askHint, error, connected, unreachable, queued, send, onLeave, onQuit, onTutorialStop, onYou, initial, account, friends, inviting, where, onLocalInvite, coachOff, onReplay, onDone, onSeeBoard }: Props) {
  const [showSettings, setShowSettings] = useState(false);
  const [offCall, setOffCall] = useState<{ call: string; why: string } | null>(null); // Learn to play: a call off the cheat sheet
  const [showInvite, setShowInvite] = useState(!!inviting);
  const [wifiInvite, setWifiInvite] = useState(false); // a partner on this Wi-Fi joins the table on this phone
  const update = useUpdate(); // a newer version is out: a dot on your avatar, and Reload at the top of its sheet
  const [showScore, setShowScore] = useState(false);
  const [picking, setPicking] = useState(false);
  const [peekLast, setPeekLast] = useState(false);
  const [hiddenHint, setHiddenHint] = useState<Hint | null>(null);
  const [openCall, setOpenCall] = useState<number | null>(null);
  const [openCard, setOpenCard] = useState<{ card: string; seat: Seat } | null>(null); // a bot's card tapped in the trick
  const [look, setLook] = useState<string | null>(null);
  const [sent, setSent] = useState<{ card: string; key: string } | null>(null); // the card played, until the server shows it
  const [holding, setHolding] = useState(false);
  const [waited, setWaited] = useState<string[]>([]); // the times someone left that you chose to wait through
  const [dealing, setDealing] = useState(false);
  const [justDealt, setJustDealt] = useState(false);
  const [lookedBack, setLookedBack] = useState<number | null>(null); // the board whose rubber-over sheet was closed
  const [reviewing, setReviewing] = useState<number | null>(null); // rubber scoring: the board whose review is open, past its score
  const [answerClosed, setAnswerClosed] = useState<string | null>(null); // Your mistakes: the puzzle whose answer was closed
  const [soFar, setSoFar] = useState(false); // Your mistakes: Tricks so far is open
  const [prefs, setPrefs] = usePrefs();
  const wide = useMedia("(min-width: 820px) and (min-height: 600px)");
  const short = useMedia("(max-height: 900px)");
  // smaller sizes for a wide screen that is low (a laptop window, an iPad on its side with the score strip): from the
  // window's height, then one step more at a time while the table is too short for the names and calls in it
  const [squeeze, setSqueeze] = useState(0);
  useEffect(() => {
    const again = () => setSqueeze(0);
    window.addEventListener("resize", again);
    return () => window.removeEventListener("resize", again);
  }, []);
  const under800 = useMedia("(max-height: 799px)");
  const under720 = useMedia("(max-height: 719px)");
  const byHeight = under720 ? 2 : under800 ? 1 : 0;
  const tier = Math.max(byHeight, squeeze);
  const low = tier >= 1;
  const lower = tier >= 2;
  const holdTimer = useRef<number | undefined>(undefined);
  const tblRef = useRef<HTMLDivElement>(null);
  const topDummy = (wide ? (lower ? SIZES.wideLower : low ? SIZES.wideLow : short ? SIZES.wideShort : SIZES.wide) : SIZES.phone).dummy;
  const dummyFit = useDummyFit(tblRef, topDummy[0], topDummy[1]); // a long suit in dummy stays clear of the trick
  // the table's height the names and calls need while bidding, at each size (the top and bottom names, the calls in
  // front of them, and a gap between)
  const NEED = [250, 212, 200];
  useLayoutEffect(() => {
    const el = tblRef.current;
    if (!wide || tier >= 2 || !el || !el.closest(".play-layout.bidding")) return;
    if (el.clientHeight < NEED[tier]) setSqueeze(tier + 1);
  });
  const tricksSeen = useRef<{ board: number; n: number }>({ board: 0, n: 0 });
  const lastPlaying = useRef<TableState | null>(null);

  const t = state?.table ?? null;
  const me = state?.you ?? state?.pending ?? "S"; // watching: seen from South, or from the seat you'll take
  const watching = !!state?.watching;
  const board = t?.board ?? 0;
  const tricksDone = t ? t.tricks_won.NS + t.tricks_won.EW : 0;
  if (t?.phase === "playing") lastPlaying.current = t;
  // a claim played out on the table goes quickly: each finished trick is on show only briefly (as the server waits)
  const claimPlaying = !!(t?.phase === "playing" ? t.claiming : t?.phase === "done" && t.result?.claim_played);
  const trickPause = claimPlaying ? CLAIM_TRICK : (state?.settings.trick_pause ?? 2) * 1000;

  // a finished trick stays in the middle for a while (the server waits as long before a bot leads)
  useEffect(() => {
    const seen = tricksSeen.current;
    if (seen.board !== board) {
      tricksSeen.current = { board, n: tricksDone };
      setHolding(false);
      return;
    }
    if (tricksDone > seen.n) {
      seen.n = tricksDone;
      setHolding(true);
      window.clearTimeout(holdTimer.current);
      holdTimer.current = window.setTimeout(() => setHolding(false), trickPause);
    } else if (tricksDone < seen.n) {
      // Undo took tricks back: count from here, so the next finished trick is held again
      seen.n = tricksDone;
      endHold();
    }
  }, [board, tricksDone, trickPause]);
  const endHold = () => {
    window.clearTimeout(holdTimer.current);
    setHolding(false);
  };

  // deal the cards around the table at the start of each board (before the first paint, so the hand never shows first)
  useLayoutEffect(() => {
    if (!t || !state || t.phase !== "bidding" || t.auction.length > 0) return;
    if (!prefs.dealAnimation || reducedMotion() || dealtBefore(`${state.room}/${t.board}`)) return;
    setDealing(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board]);
  const dealDone = useCallback(() => {
    setDealing(false);
    setJustDealt(true);
    window.setTimeout(() => setJustDealt(false), 600);
  }, []);

  // a refused play puts the card back in your hand; one still on its way stays on the table until it gets there
  useEffect(() => {
    if (!sent) return;
    if (error) setSent(null);
    if (queued) return;
    const timer = window.setTimeout(() => setSent(null), 4000);
    return () => window.clearTimeout(timer);
  }, [sent, error, queued]);

  // an opened bid's meaning belongs to one board
  useEffect(() => {
    setOpenCall(null);
    setOpenCard(null);
  }, [board]);

  const pos = compass(me);
  const at = useMemo(
    () => ({ [pos.top]: "top", [pos.left]: "left", [pos.right]: "right", [pos.bottom]: "bottom" }) as Record<Seat, Where>,
    [pos.top, pos.left, pos.right, pos.bottom],
  );
  const lookAt = useCallback((c: string | null) => setLook(c), []);

  if (!state)
    return (
      <div className="center muted">
        {where === "local" ? (
          <>
            <span className="spinner" aria-hidden="true" />
            <p>Getting the game ready on this {deviceName() || "device"}…</p>
            <p className="small">This takes a few seconds.</p>
          </>
        ) : (
          <>
            <p>{connected ? "Joining…" : "Connecting…"}</p>
            {unreachable && <p className="small">No internet. This table is on the server, so it picks up when you're back online.</p>}
          </>
        )}
        <button className="chip" onClick={onLeave}>
          Back to start
        </button>
      </div>
    );

  const nameOf = (s: Seat) =>
    state.bots.includes(s) ? `Bot ${SEAT_NAME[s]}` : state.players[s] ? `${state.players[s]}` : `${SEAT_NAME[s]} (waiting)`;
  const changeSettings = (s: Partial<Settings>) => {
    // the next new table starts with these (an account keeps its own on the server)
    const keep = Object.fromEntries(Object.entries(s).filter(([k]) => (REMEMBERED as readonly string[]).includes(k)));
    if (Object.keys(keep).length) setPrefs({ table: { ...prefs.table, ...keep } });
    send({ type: "settings", ...s });
  };
  const mine = (me === "N" || me === "S" ? 1 : -1) * state.totals.score_ns;
  // a deal played again, or Your mistakes (puzzles): never scored, so no score in the corner
  const rp = state.settings.replay ?? null;
  // other people at the table: playing a deal again would leave them waiting, so it's offered in hand history instead
  const othersHere = (["N", "E", "S", "W"] as Seat[]).some((s) => s !== state.you && !state.bots.includes(s) && !!state.players[s]);
  const puzzle = rp?.puzzles ? rp : null;
  const lastPuzzle = !!puzzle && (puzzle.n ?? 0) >= (puzzle.of ?? 0);
  const nextPuzzle = () => (lastPuzzle ? (onDone ?? onLeave)() : send({ type: "puzzle_next" }));

  const header = (
    <header className="topbar">
      <button className="icon menu-btn" onClick={() => setShowSettings(true)} aria-label="Menu">
        ☰
      </button>
      {t && (
        // each part keeps to one line; when the line is too narrow (iPhone SE) the parts wrap, and the dot that would
        // start the new line is clipped (styles.css, .boardinfo .parts)
        <span className="boardinfo joined">
          <span className="parts">
            {puzzle ? (
              <span>
                Your mistakes · {puzzle.n} of {puzzle.of}
              </span>
            ) : (
              <span>
                Board {t.board} · {t.vulnerability === "None" ? "none vul" : t.vulnerability === "Both" ? "all vul" : `${t.vulnerability} vul`}
              </span>
            )}
            {rp && !puzzle && <span className="offline">replay</span>}
            {where === "local" ? (
              <span className="offline">local</span>
            ) : where === "wifi" ? (
              <span className="offline">on Wi-Fi</span>
            ) : (
              !connected && <span className="offline">offline</span>
            )}
            {state.settings.ai_coach && !coachOff && <span className="coach-note">AI coach</span>}
          </span>
        </span>
      )}
      {/* top right: the score, then you (with a dot when a newer version is out) */}
      <div className="corner">
        <button className="you" onClick={() => onYou()} aria-label={update ? "You and this device, update available" : "You and this device"}>
          <span className="avatar">{initial ?? <PersonIcon />}</span>
          {update && <span className="update-dot" aria-hidden="true" />}
        </button>
        {puzzle ? (
          <button className="skip" onClick={nextPuzzle}>
            {lastPuzzle ? "Done" : "Skip"}
          </button>
        ) : rp ? null : state.rubber ? (
          // rubber: just this rubber's totals; the full score pad opens on a tap
          <button className="score-btn wethey" onClick={() => setShowScore(true)} aria-label="Score sheet">
            <span>We {state.rubber.totals[me === "N" || me === "S" ? "NS" : "EW"]}</span>
            <span>They {state.rubber.totals[me === "N" || me === "S" ? "EW" : "NS"]}</span>
          </button>
        ) : (
          <button className={`score-btn ${mine >= 0 ? "plus" : "minus"}`} onClick={() => setShowScore(true)} aria-label="Score sheet">
            {signed(mine)}
          </button>
        )}
      </div>
    </header>
  );

  const practiceBar = state.settings.tutorial ? (
    <TutorialTable state={state} me={me} send={send} onStop={onTutorialStop ?? onLeave} />
  ) : state.settings.practice && (
    <div className="practice-bar">
      <span>Practicing: {state.settings.practice_title}</span>
      <button className="small" onClick={() => changeSettings({ practice: null })}>
        Stop
      </button>
    </div>
  );

  const settings = showSettings && (
    <SettingsPanel
      settings={state.settings}
      room={state.room}
      where={where}
      onChange={changeSettings}
      onClose={() => setShowSettings(false)}
      onLeave={onLeave}
      onQuit={onQuit}
      others={Object.keys(state.players).length > 1}
      onAccount={() => {
        setShowSettings(false);
        onYou("ai");
      }}
      onInvite={
        where === "local"
          ? () => {
              setShowSettings(false);
              // with internet the table moves to the server for a friend to join; with none, a partner on this Wi-Fi
              void (onLocalInvite?.() ?? Promise.resolve(false)).then((moved) => moved || setWifiInvite(true));
            }
          : account?.user
          ? () => {
              setShowSettings(false);
              setShowInvite(true);
            }
          : undefined
      }
      onChangeSeat={
        state.you
          ? () => {
              setShowSettings(false);
              setPicking(true);
            }
          : undefined
      }
      onSkip={
        state.can_skip && state.table && state.table.phase !== "done"
          ? () => {
              setShowSettings(false);
              send({ type: "skip" });
            }
          : undefined
      }
    />
  );

  const inviteSheet = (
    <>
      {showInvite && account?.user && <InviteSheet account={account} view={friends ?? null} room={state.room} onClose={() => setShowInvite(false)} />}
      {wifiInvite && (
        <Suspense fallback={null}>
          <WifiInvite onClose={() => setWifiInvite(false)} onJoined={() => setWifiInvite(false)} />
        </Suspense>
      )}
    </>
  );
  const scoreSheet = showScore && <ScoreSheet state={state} me={me} onClose={() => setShowScore(false)} />;
  const picker = (state.choosing || picking) && (
    <SeatPicker state={state} send={send} onLeave={onLeave} onClose={state.choosing ? undefined : () => setPicking(false)} />
  );
  const others = state.watchers?.length ? `Watching: ${state.watchers.join(", ")}` : "";
  // someone else at the table left: play on with a bot, or wait (and a line saying so)
  const goneSeats = watching || !state.you ? [] : (Object.keys(state.gone ?? {}) as Seat[]).filter((s) => s !== me);
  const goneKey = (s: Seat) => `${s}/${state.gone![s]!.since}`;
  const asking = goneSeats.find((s) => !state.gone![s]!.bot && !waited.includes(goneKey(s)));
  const goneSheet = asking && (
    <GoneSheet
      seat={asking}
      gone={state.gone![asking]!}
      onBot={(s) => send({ type: "bot_for", seat: s })}
      onWait={() => setWaited([...waited, goneKey(asking)])}
    />
  );
  const goneBar = !asking && goneSeats.length > 0 && (
    <div className="watch-bar gone-bar">
      {goneSeats.map((s) => {
        const g = state.gone![s]!;
        return g.bot ? (
          <span key={s}>A bot plays for {g.name}</span>
        ) : (
          <span key={s} className="gone-wait">
            Waiting for {g.name}
            <button className="chip" onClick={() => send({ type: "bot_for", seat: s })}>
              Play on with a bot
            </button>
          </span>
        );
      })}
    </div>
  );
  // Skip hand with a person as partner: the partner says yes or no; the one who asked sees a line until then
  const skipAsk = !watching && t && t.phase !== "done" ? state.skip_ask : null;
  const skipSheet = skipAsk && skipAsk.by !== me && state.you && (
    <SkipSheet
      name={skipAsk.name}
      onSkip={() => send({ type: "skip_answer", agree: true })}
      onPlay={() => send({ type: "skip_answer", agree: false })}
    />
  );
  const skipBar = skipAsk && skipAsk.by === me ? (
    <div className="watch-bar gone-bar">
      <span className="gone-wait">
        Asked {nameOf(partnerOf(me))} to skip this hand
        <button className="chip" onClick={() => send({ type: "skip_answer" })}>
          Cancel
        </button>
      </span>
    </div>
  ) : !watching && state.skip_no ? (
    <div className="watch-bar gone-bar">
      <span className="gone-wait">
        {state.skip_no} wants to play this hand
        <button className="chip" onClick={() => send({ type: "skip_answer" })}>
          OK
        </button>
      </span>
    </div>
  ) : null;
  const watchBar = watching ? (
    <div className="watch-bar">
      <span>Watching{state.pending ? ` · you sit ${SEAT_NAME[state.pending]} from the next board` : ""}</span>
      <button className="chip" onClick={() => setPicking(true)}>
        {state.pending ? "Change" : "Take a seat"}
      </button>
    </div>
  ) : (
    others && <div className="watch-bar">{others}</div>
  );
  const undoOn = state.settings.undo;
  const undo = () => {
    endHold();
    setPeekLast(false);
    send({ type: "undo" });
  };

  if (!t) {
    const share = `${location.origin}/?room=${state.room}`;
    return (
      <div className="app">
        {header}
        <div className="waiting">
          <p>Code</p>
          <div className="room-code">{state.room}</div>
          <p className="muted-on-felt">or send a link:</p>
          <code>{share}</code>
          {navigator.share && (
            <button onClick={() => navigator.share({ title: APP_NAME, text: "Join my bridge table", url: share })}>
              Share link
            </button>
          )}
          <p className="muted-on-felt">Waiting for partner…</p>
          <button onClick={() => send({ type: "settings", solo: true })}>Play with a bot instead</button>
          <button onClick={() => send({ type: "next_board" })} disabled={state.waiting_for_partner}>
            Start
          </button>
        </div>
        {settings}
        {inviteSheet}
        {scoreSheet}
        {picker}
        {error && <div className="toast">{error}</div>}
      </div>
    );
  }

  // while the last trick of the board is on show, keep the table as it was during the play
  const snap = lastPlaying.current;
  // (not after a claim that ended at once: the hands it would keep weren't played out on the table)
  const finishing =
    t.phase === "done" && holding && snap !== null && snap.board === t.board && !!t.last_trick && (!t.result?.claimed || !!t.result.claim_played);
  const atServer: TableState = finishing
    ? {
        ...snap!,
        trick: t.trick,
        last_trick: t.last_trick,
        tricks_won: t.tricks_won,
        your_turn: false,
        legal_cards: [],
        turn: null,
        claiming: null,
        hands: Object.fromEntries(
          Object.entries(snap!.hands).map(([s, h]) => [s, h ? h.filter((c) => !t.last_trick!.cards.some((x) => x.card === c)) : null]),
        ) as TableState["hands"],
        counts: { N: 0, E: 0, S: 0, W: 0 },
      }
    : t;
  // a card you tap goes onto the table at once, so your hand doesn't light up again while the server answers
  const turnKey = `${t.board}/${Object.values(t.counts).reduce((a, n) => a + n, 0)}`;
  // Your mistakes: the answer, once given, until the player plays on; a card answer sits in the trick meanwhile
  const answer = puzzle && !puzzle.playing_on ? puzzle.answer ?? null : null;
  const puzzleOpen = !!puzzle && !puzzle.playing_on && !answer;
  const view: TableState =
    answer?.kind === "card" && answer.card && atServer.turn && atServer.phase === "playing"
      ? playedAhead(atServer, atServer.turn, answer.card)
      : sent && sent.key === turnKey && atServer.turn && atServer.your_turn
      ? playedAhead(atServer, atServer.turn, sent.card)
      : atServer;

  const size = wide ? (lower ? SIZES.wideLower : low ? SIZES.wideLow : short ? SIZES.wideShort : SIZES.wide) : SIZES.phone;
  const bidding = view.phase === "bidding";
  const myTurnToPlay = view.phase === "playing" && view.your_turn;
  const playable = (s: Seat) => (myTurnToPlay && view.turn === s ? view.legal_cards : []);
  const play = (card: string) => {
    endHold();
    if (!puzzleOpen) setSent({ card, key: turnKey }); // a puzzle's answer is shown from the server's answer instead
    send({ type: "play", card });
  };
  // a close call's firmer answer to a hint the player already closed with OK stays closed
  const hidden =
    hint === hiddenHint ||
    (hint?.phase === "playing" && hint.firmer && hiddenHint?.phase === "playing" && !!hint.decision && hint.decision === hiddenHint.decision);
  const shownHint = hint && !hidden && view.your_turn ? hint : null;
  const hintedCard = shownHint?.phase === "playing" ? shownHint.card : undefined;
  const hintedCall = shownHint?.phase === "bidding" ? shownHint.call : undefined;
  const lastBid = [...view.auction].reverse().find((e) => /^[1-7]/.test(e.call))?.call ?? null;
  const trump = view.contract?.strain ?? "N";

  const call = (c: string) => {
    // Learn to play step 6: a call off the cheat sheet gets a second look first
    const why = callCheck(state, c);
    if (why) setOffCall({ call: c, why });
    else send({ type: "call", call: c });
  };
  const offSheet = offCall && (
    <div className="sheet-backdrop" onClick={() => setOffCall(null)}>
      <div className="sheet tut-again" role="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-top">
          <h2>Not this time</h2>
          <button className="close" aria-label="Close" onClick={() => setOffCall(null)}>
            ✕
          </button>
        </div>
        <p>
          <SuitText text={offCall.why} />
        </p>
        <div className="sheet-actions tut-endbtns">
          <button
            onClick={() => {
              send({ type: "call", call: offCall.call });
              setOffCall(null);
            }}
          >
            Bid it anyway
          </button>
          <button className="primary" onClick={() => setOffCall(null)}>
            Try again
          </button>
        </div>
      </div>
    </div>
  );

  // Each hand's name, with the contract beside declarer. While the cards are played each side's tricks show once:
  // declarer's side by declarer (taken/needed), the defenders by you, or else by the defender on your right.
  const c = view.phase === "playing" ? view.contract : null;
  const counter = (s: Seat) =>
    !!c && (s === c.declarer || (!sameSide(s, c.declarer) && (sameSide(me, c.declarer) ? s === pos.right : s === me)));
  const label = (s: Seat, where: Where, inflow = false) => {
    const turn = view.turn === s && view.phase !== "done";
    const ours = c ? sameSide(s, c.declarer) : false;
    const won = view.tricks_won[sameSide(s, "N") ? "NS" : "EW"];
    return (
      <span className={`seatlbl ${where} ${turn ? "turn" : ""} ${inflow ? "inflow" : ""}`}>
        {(view.dummy === s || (view.phase === "bidding" && view.dealer === s)) && (
          <span className="role">{view.dummy === s ? "Dummy" : "Dealer"}</span>
        )}
        <span className="nm">{nameOf(s)}</span>
        {c && counter(s) && (
          <span className="lb tricks" aria-label={`${won} tricks${ours ? ` of ${c.level + 6} needed` : ""}`}>
            • {won}
            {ours && <small>/{c.level + 6}</small>}
          </span>
        )}
        {c && c.declarer === s && (
          <span className={`lb contract s-${c.strain} ${isRed(c.strain) ? "red" : ""}`}>
            <SuitText text={`${c.level}${SUIT_SYMBOL[c.strain]}${c.doubled === 2 ? "XX" : c.doubled === 1 ? "X" : ""}`} />
          </span>
        )}
      </span>
    );
  };

  const otherSeat = (s: Seat, where: "top" | "left" | "right") => {
    const cards = view.hands[s];
    const showing = cards && view.phase === "playing" && (!watching || s === view.dummy);
    return (
      <>
        {showing ? (
          <div className={`dummy-wrap ${where}`}>
            {where !== "top" && label(s, where, true)}
            <Dummy
              cards={cards}
              trump={trump}
              playable={playable(s)}
              onPlay={myTurnToPlay ? play : undefined}
              hinted={hintedCard}
              w={where === "top" ? Math.round(size.dummy[0] * (dummyFit.scale ?? 1)) : size.sideDummy[0]}
              h={where === "top" ? Math.round(size.dummy[1] * (dummyFit.scale ?? 1)) : size.sideDummy[1]}
              layout={where !== "top" ? "side" : wide ? "columns" : "row"}
            />
            {where === "top" && label(s, where, true)}
          </div>
        ) : (
          view.counts[s] > 0 && (
            <div className={`seatfan ${where}`}>
              <Fan key={board} cards={view.counts[s]} w={size.back[0]} h={size.back[1]} spread={30} className={justDealt ? "dealt" : ""} />
            </div>
          )
        )}
        {!showing && label(s, where)}
        {bidding && (
          <BidTiles seat={s} auction={view.auction} where={where} open={openCall} onOpen={setOpenCall} />
        )}
      </>
    );
  };

  const shown = peekLast && view.last_trick ? view.last_trick : holding && view.last_trick && !(view.trick?.cards.length) ? view.last_trick : view.trick;
  const showingHeld = shown === view.last_trick && holding && !peekLast;
  const winner = showingHeld ? view.last_trick?.winner : undefined;
  const winCard = winner ? view.last_trick!.cards.find((c) => c.seat === winner)?.card : undefined;
  // during the play dummy is "dummy", not the bot or player sitting there
  const isDummy = (s: Seat) => view.phase === "playing" && s === view.dummy && s !== me;
  const playName = (s: Seat) => (isDummy(s) ? "Dummy" : nameOf(s));
  const claiming = view.claiming ?? (finishing ? snap!.claiming : null);
  const claimNotice = claiming && (claiming.by === me ? "You claim the rest" : `${nameOf(claiming.by)} claims the rest`);
  const banner = claimNotice ? (
    claimNotice
  ) : winner && winCard && (
    <>
      <SuitText text={`${playName(winner)} wins with ${cardLabel(winCard)}`} /> · tap to go on
      <span className="holdbar" style={{ animationDuration: `${trickPause}ms` }} />
    </>
  );

  const status = (() => {
    // no one to wait for, as while the last trick is on show or a claim plays out (its notice is on the felt)
    if (view.phase === "done" || !view.turn || claimNotice) return "";
    if (view.your_turn && puzzleOpen) {
      // Your mistakes asks the question the board asked then
      if (bidding) return "Your call?";
      const what = view.turn === me ? "your play" : isDummy(view.turn as Seat) ? "play from dummy" : `play from ${nameOf(view.turn as Seat)}'s hand`;
      return `Trick ${puzzle?.trick ?? tricksDone + 1}: ${what}?`;
    }
    if (view.your_turn) {
      if (bidding) return "Your call";
      return view.turn === me ? "Your card" : isDummy(view.turn as Seat) ? "Play from dummy" : `Play from ${nameOf(view.turn as Seat)}'s hand`;
    }
    const turn = view.turn as Seat;
    // declarer plays dummy's cards: name who is to play, not the seat whose card it is
    const who = bidding || !view.controller || view.controller === turn
      ? `${playName(turn)} to ${bidding ? "call" : "play"}`
      : `${nameOf(view.controller)} to play from ${turn === view.dummy ? "dummy" : `${nameOf(turn)}'s hand`}`;
    return watching ? who : `${who}…`;
  })();
  const hintButton = view.your_turn && state.settings.hints && !shownHint && !puzzleOpen && (
    <button className="chip" disabled={hintPending} aria-busy={hintPending} onClick={askHint}>
      {hintPending ? "Thinking…" : "Hint"}
    </button>
  );
  const claimButton = view.can_claim && (
    <button className="chip gold" onClick={() => send({ type: "claim" })} title="Take every remaining trick">
      Claim
    </button>
  );
  const hintText =
    shownHint &&
    (shownHint.phase === "bidding" ? (
      <SuitText text={`${callLabel(shownHint.call)}: ${shownHint.text}`} />
    ) : (
      <>
        <SuitText
          text={`Try ${cardLabel(shownHint.card)}${shownHint.seat === me ? "" : isDummy(shownHint.seat) ? " from dummy" : ` from ${nameOf(shownHint.seat)}'s hand`}${
            shownHint.equal.length > 1 ? ` (as good: ${shownHint.equal.filter((c) => c !== shownHint.card).map(cardLabel).join(", ")})` : ""
          }.`}
        />
        {shownHint.signal && (
          <>
            {" "}
            <SuitText text={shownHint.signal} />
          </>
        )}
        {shownHint.odds && c ? (
          <span className="hint-odds">
            <SuitText
              text={`${shownHint.goal === "beat" ? "Beats" : "Makes"} ${callLabel(`${c.level}${c.strain}`)}: ${shownHint.odds
                .map((o) => `${cardLabel(o.card)}\u00a0${o.pct}%`)
                .join(" · ")}`}
            />
          </span>
        ) : null}
        {shownHint.extra ? (
          <span className="hint-odds">
            <SuitText
              text={`But for an extra trick: ${shownHint.extra.odds.map((o) => `${cardLabel(o.card)}\u00a0${o.pct}%`).join(" · ")}`}
            />
          </span>
        ) : null}
        {shownHint.firming ? <span className="hint-odds hint-firming">Close call: checking more layouts…</span> : null}
      </>
    ));

  const opened = openCall !== null ? view.auction[openCall] : null;
  const cardWhy = openCard && view.card_why?.[openCard.card];
  // a bot's call or card opens its explanation straight away; a person's call shows its meaning in the bar
  const whyPopup = cardWhy && openCard ? (
    <CardWhy card={openCard.card} seat={openCard.seat} why={cardWhy} dummy={view.dummy} contract={view.contract} room={state.room} board={view.board} onClose={() => setOpenCard(null)} />
  ) : opened?.why ? (
    <BidWhy entry={opened} index={openCall!} room={state.room} board={view.board} onClose={() => setOpenCall(null)} />
  ) : null;
  const bidNote = queued?.slow ? (
    <span className="text sending">
      <SuitText text={`Waiting for connection to send ${queued.card ? cardLabel(queued.card) : callLabel(queued.call ?? "")}…`} />
    </span>
  ) : opened && !opened.why ? (
    <>
      <span className="text">
        <strong>{nameOf(opened.seat)}</strong>: <SuitText text={callLabel(opened.call)} />
        {opened.meaning.alert && <span className="badge">alert</span>}
        {opened.meaning.forcing && <span className="badge">forcing</span>} <SuitText text={opened.meaning.text} />
        {opened.meaning.hcp && (
          <span className="muted-on-felt">
            {" "}
            · HCP {opened.meaning.hcp[0]}–{opened.meaning.hcp[1]}
          </span>
        )}
      </span>
      <button className="chip" onClick={() => setOpenCall(null)}>
        OK
      </button>
    </>
  ) : answer && puzzle && answerClosed === `${puzzle.key}/${puzzle.n}` ? (
    <>
      <span className="text yours">
        {answer.right ? "Right" : "Better"}:{" "}
        <SuitText text={answer.kind === "card" ? cardLabel(answer.right ? answer.card! : answer.better!) : callLabel(answer.right ? answer.call! : answer.system_call!)} />
      </span>
      <button className="chip" onClick={() => setAnswerClosed(null)}>
        Answer
      </button>
    </>
  ) : shownHint ? (
    <>
      <span className="text">
        💡 {hintText} <HintsInfo />
      </span>
      {claimButton}
      <button className="chip" onClick={() => setHiddenHint(shownHint)}>
        OK
      </button>
    </>
  ) : (
    <>
      <span className={`text ${view.your_turn ? "yours" : ""}`}>
        {status}
        {view.your_turn && view.auction.length === 0 && ` · you deal`}
      </span>
      {claimButton}
      {view.phase === "bidding" && (
        <a className="chip" href={CHEAT_SHEET} target="_blank" rel="noopener noreferrer">
          Cheat sheet
        </a>
      )}
      {/* Claim, Last trick, Hint, Undo; at a puzzle, Tricks so far instead, as the player didn't see them played */}
      {puzzleOpen && view.phase === "playing" && (view.played?.length ?? 0) > 0 ? (
        <button className="chip" onClick={() => setSoFar(true)}>
          Tricks so far
        </button>
      ) : view.phase === "playing" && view.last_trick && (
        <button className="chip" onClick={() => setPeekLast(!peekLast)}>
          {peekLast ? "Hide" : "Last trick"}
        </button>
      )}
      {hintButton}
      {/* Undo always sits at the far right */}
      {undoOn && view.can_undo && (
        <button className="chip undo" onClick={undo} aria-label="Undo: take back the last call or card" title="Undo">
          <UndoIcon />
          Undo
        </button>
      )}
    </>
  );

  const myCards = view.hands[me] ?? [];
  const showResult = t.phase === "done" && t.result && !finishing;
  const endedRubber = showResult ? state.rubber?.finished.find((f) => f.board === t.board) : undefined;
  // a player sees the rubber's end on the score that comes first; a watcher sees it over the review
  const rubberOver = endedRubber && !state.you && lookedBack !== t.board ? endedRubber : undefined;
  // rubber scoring: a player sees the score first, then the review if they ask for it
  const scoreFirst = showResult && !!state.rubber && !!state.you && reviewing !== t.board;
  // the next deal waits for everyone at the table to tap Next board
  const waitingFor = state.next_waiting ?? [];
  const nextLabel = state.next_ready
    ? waitingFor.length ? `Waiting for ${waitingFor.join(" and ")}` : "Dealing…"
    : "Next board";
  const canNext = !state.waiting_for_partner && !state.next_ready;
  const next = () => send({ type: "next_board" });

  // Feedback opens under the score strip: the table keeps its size and the page scrolls up to show the form.
  // Measured on the tap, before the details opens and the strip grows.
  const feedbackTap = (e: React.MouseEvent<HTMLElement>) => {
    const el = e.currentTarget.parentElement as HTMLDetailsElement;
    const felt = el.closest(".app")?.querySelector<HTMLElement>(".play-layout");
    const opening = !el.open;
    if (felt) felt.style.height = opening ? `${felt.offsetHeight}px` : "";
    if (opening) setTimeout(() => el.scrollIntoView({ block: "end", behavior: "smooth" }), 30);
  };

  return (
    <div className={`app ${wide ? "wide" : ""} ${wide && short ? "short" : ""} ${wide && low ? "low" : ""} ${wide && lower ? "lower" : ""}`}>
      {header}
      {practiceBar}
      {watchBar}
      {goneBar}
      {goneSheet}
      {skipBar}
      {skipSheet}

      {rubberOver && (
        <RubberOver
          rubber={rubberOver}
          me={me}
          watching={watching}
          onQuit={onQuit ?? onLeave}
          onLookBack={() => setLookedBack(t.board)}
        />
      )}
      {scoreFirst ? (
        <BoardScore
          result={t.result!}
          rubber={state.rubber!}
          me={me}
          onReview={() => setReviewing(t.board)}
          onNext={next}
          canNext={canNext}
          nextLabel={nextLabel}
          onQuit={onQuit ?? onLeave}
        />
      ) : showResult ? (
        <ResultPanel
          result={t.result!}
          me={me}
          nameOf={nameOf}
          watching={watching}
          onNext={!state.you ? undefined : puzzle ? nextPuzzle : rp ? onDone ?? onLeave : next}
          canNext={rp ? true : canNext}
          nextLabel={puzzle ? (lastPuzzle ? "Done" : "Next") : rp ? "Done" : nextLabel}
          onReplay={
            !state.you || !t.result
              ? undefined
              : rp
              ? (from) => send({ type: "replay", from }) // the same table plays it again
              : onReplay && !othersHere ? ((from) => onReplay(replaySpec({ ...t.result!, dealer: t.dealer, vulnerability: t.vulnerability }, me, from, state.settings))) : undefined
          }
          onScore={state.rubber && state.you ? () => setReviewing(null) : undefined}
          onUndo={undoOn && t.can_undo ? undo : undefined}
          help={state.help}
          auction={<AuctionView auction={t.auction} dealer={t.dealer} turn={null} room={state.room} board={t.board} />}
          play={
            t.result?.play?.length ? (
              <PlayView play={t.result.play} whys={t.card_why ?? {}} dummy={t.dummy} contract={t.contract} room={state.room} board={t.board} />
            ) : undefined
          }
        />
      ) : (
        <div className={`play-layout ${bidding ? "bidding" : "playing"} ${dealing ? "dealing" : ""}`}>
          <div ref={tblRef} className={`tbl ${view.phase === "playing" && view.dummy ? `dummy-${at[view.dummy]}` : ""}`}>
            {otherSeat(pos.top, "top")}
            {otherSeat(pos.left, "left")}
            {otherSeat(pos.right, "right")}
            {label(me, "bottom")}
            {bidding && <BidTiles seat={me} auction={view.auction} where="bottom" open={openCall} onOpen={setOpenCall} />}
            {!bidding && (
              <TrickArea
                trick={shown}
                me={me}
                banner={banner}
                top={dummyFit.top}
                onTap={showingHeld ? endHold : undefined}
                explained={view.card_why}
                onCard={(card, seat) => setOpenCard(openCard?.card === card ? null : { card, seat })}
              />
            )}
          </div>

          <div className="side">
            {watching ? (
              <>
                {bidding ? (
                  <AuctionView auction={view.auction} dealer={view.dealer} turn={view.turn} room={state.room} board={view.board} />
                ) : (
                  <div className="bidnote play-note">{bidNote}</div>
                )}
              </>
            ) : bidding ? (
              <>
                <BiddingBox
                  legal={view.legal_calls}
                  meanings={view.call_meanings}
                  lastBid={lastBid}
                  hinted={hintedCall}
                  onCall={call}
                  onLook={lookAt}
                  disabled={!view.your_turn || !!queued}
                  note={bidNote}
                />
                <PointsPanel
                  cards={myCards}
                  auction={view.auction}
                  me={me}
                  partnerName={nameOf(partnerOf(me))}
                  target={look}
                  detail={prefs.pointsDetail}
                  onDetail={(on) => setPrefs({ pointsDetail: on })}
                />
              </>
            ) : (
              <>
                <div className="bidnote play-note">{bidNote}</div>
                <details className="auction-recap">
                  <summary>Auction</summary>
                  <AuctionView auction={view.auction} dealer={view.dealer} turn={null} room={state.room} board={view.board} />
                </details>
              </>
            )}
          </div>

          <Fan
            key={board}
            className={`myfan ${justDealt ? "dealt" : ""}`}
            cards={watching && !view.hands[me] ? view.counts[me] : myCards}
            w={size.hand[0]}
            h={size.hand[1]}
            spread={HAND_SPREAD}
            playable={playable(me)}
            onPlay={myTurnToPlay ? play : undefined}
            hinted={hintedCard}
            trump={trump}
          />
          {dealing && <DealAnimation dealer={view.dealer} at={at} onDone={dealDone} />}
        </div>
      )}
      <footer className="history">
        {/* bottom left: Feedback about this board, opened in place on the felt; the deal and play go with the note */}
        {state.you && t && loadToken() && (
          <details className="whats-new table-feedback" key={t.board}>
            <summary onClick={feedbackTap}>Feedback</summary>
            <div className="table-feedback-panel">
              <Feedback
                bare
                about={{ board: { room: state.room, board: t.board } }}
                intro={
                  showResult
                    ? "The deal, play and review go with your note."
                    : "The deal and play so far go with your note."
                }
                placeholder="What happened?"
              />
            </div>
          </details>
        )}
        {(rp ? [] : state.history) // a deal played again isn't a board of this table's
          .slice(-5)
          .reverse()
          .map((h) => (
            <span key={h.board}>
              <span className="muted-on-felt">Bd {h.board}</span>{" "}
              <SuitText text={h.contract ? `${h.contract.level}${SUIT_SYMBOL[h.contract.strain]} ${h.contract.declarer}` : "Passed"} />{" "}
              <b>{signed((me === "N" || me === "S" ? 1 : -1) * h.score_ns)}</b>
            </span>
          ))}
      </footer>
      {settings}
      {inviteSheet}
      {scoreSheet}
      {whyPopup}
      {offSheet}
      {picker}
      {answer && puzzle && answerClosed !== `${puzzle.key}/${puzzle.n}` && (
        <PuzzleSheet
          answer={answer}
          last={lastPuzzle}
          fromDummy={answer.seat !== me && answer.seat === view.dummy}
          onNext={nextPuzzle}
          onRetry={() => send({ type: "puzzle_retry" })}
          onRemove={() => send({ type: "puzzle_remove" })}
          onPlayOn={() => send({ type: "play_on" })}
          onAgain={() => send({ type: "replay" })}
          onBoard={onSeeBoard && puzzle.key ? () => onSeeBoard(puzzle.key!) : undefined}
          onClose={() => setAnswerClosed(`${puzzle.key}/${puzzle.n}`)}
        />
      )}
      {soFar && view.played && (
        <div className="sheet-backdrop" onClick={() => setSoFar(false)}>
          <div className="sheet" role="dialog" onClick={(e) => e.stopPropagation()}>
            <div className="sheet-top">
              <h2>Tricks so far</h2>
              <button className="close" aria-label="Close" onClick={() => setSoFar(false)}>
                ✕
              </button>
            </div>
            <PlayView play={view.played} whys={view.card_why ?? {}} dummy={view.dummy} contract={view.contract} room={state.room} board={view.board} />
          </div>
        </div>
      )}
      {error && <div className="toast">{error}</div>}
    </div>
  );
}
