import { useEffect, useState } from "react";
import { deviceName } from "../connection";
import { botsHere, offlineReady, offlineSupported, onOfflineProgress, onSpeedChecked, prepareOffline, setBotsHere, speedVsServer } from "../offline";
import { PlayLocallyInfo } from "./Explain";
import type { Prefs } from "../prefs";

/** Choices kept on this phone or tablet only: they change nothing for the other players. */
export default function DeviceSettings({ prefs, onPrefs }: { prefs: Prefs; onPrefs: (p: Partial<Prefs>) => void }) {
  return (
    <>
      <h3>On this device</h3>
      <label className="toggle">
        <input type="checkbox" checked={prefs.dealAnimation} onChange={(e) => onPrefs({ dealAnimation: e.target.checked })} />
        <span>
          <strong>Dealing animation</strong>
          <br />
          <span className="muted">Off when Reduce Motion is on.</span>
        </span>
      </label>
      <label className="toggle">
        <input type="checkbox" checked={prefs.largeText} onChange={(e) => onPrefs({ largeText: e.target.checked })} />
        <span>
          <strong>Larger text</strong>
          <br />
          <span className="muted">Bigger names, bids, hints and points.</span>
        </span>
      </label>
      <label className="toggle">
        <input type="checkbox" checked={prefs.fourColour} onChange={(e) => onPrefs({ fourColour: e.target.checked })} />
        <span>
          <strong>Four-color suits</strong>
          <br />
          <span className="muted">Spades black, hearts red, diamonds blue, clubs green.</span>
        </span>
      </label>
    </>
  );
}

/** "This iPhone thinks at 1.5× the server's speed.", from the monthly speed check (offline.ts). */
export function speedLine(ratio: number, device: string): string {
  const r = Math.round(ratio * 10) / 10;
  return r >= 0.9 && r <= 1.1 ? `This ${device} thinks at about the server's speed.` : `This ${device} thinks at ${r}× the server's speed.`;
}

/** Where bot tables are played, in the ☰ menu: on this phone (the default, and the only way with no internet) or on
 * the server. A change applies at the end of the board (App.tsx moves the table). `server` says why this table is on
 * the server for now although the box is ticked: another person is at it, or an invite is out. */
export function BotsHere({ server }: { server?: string }) {
  const [here, setHere] = useState(botsHere);
  const [ready, setReady] = useState(offlineReady);
  const [got, setGot] = useState(0);
  const [speed, setSpeed] = useState(speedVsServer);
  const device = deviceName() || "device";
  useEffect(() => onSpeedChecked(() => setSpeed(speedVsServer())), []);
  useEffect(() => {
    const off = onOfflineProgress((done) => {
      setGot(done);
      if (done >= 1) setReady(offlineReady());
    });
    if (here && !offlineReady()) void prepareOffline().then(() => setReady(offlineReady()));
    return () => void off();
  }, [here]);
  if (!offlineSupported()) return null;
  return (
    <>
      <label className="toggle">
        <input
          type="checkbox"
          checked={here}
          onChange={(e) => {
            setBotsHere(e.target.checked);
            setHere(e.target.checked);
          }}
        />
        <span>
          <strong>Play locally (without internet)</strong> <PlayLocallyInfo device={device} />
          <br />
          <span className="muted">
            {!here
              ? `The server plays the bots. This ${device} takes over if the internet drops.`
              : server && ready
                ? server
                : ready
                  ? `Bots play on this ${device}, with or without internet.`
                  : `Getting ready to play without internet… ${Math.round(got * 100)}%`}
          </span>
          {speed != null && (
            <>
              <br />
              <span className="muted">{speedLine(speed, device)}</span>
            </>
          )}
        </span>
      </label>
    </>
  );
}
