import type { ReactElement } from "react";

/**
 * A suit symbol drawn as a shape rather than a font character, so it is tall, clear and the same on every device.
 * It takes the color of the text around it and is 1em tall.
 */
const SHAPES: Record<string, ReactElement> = {
  S: <path d="M50 3C40 22 4 44 4 70c0 18 14 29 29 29 7 0 12-3 14-6-1 12-6 18-14 23h34c-8-5-13-11-14-23 2 3 7 6 14 6 15 0 29-11 29-29C96 44 60 22 50 3z" />,
  H: <path d="M50 117C38 98 4 76 4 42 4 20 18 6 34 6c9 0 14 6 16 14 2-8 7-14 16-14 16 0 30 14 30 36 0 34-34 56-46 75z" />,
  D: <path d="M50 2C60 26 74 44 92 60 74 76 60 94 50 118 40 94 26 76 8 60 26 44 40 26 50 2z" />,
  C: (
    <>
      <circle cx="50" cy="29" r="23" />
      <circle cx="25" cy="66" r="23" />
      <circle cx="75" cy="66" r="23" />
      <path d="M42 40h16l-4 26c1 22 5 36 15 50H31c10-14 14-28 15-50z" />
    </>
  ),
};
const NAME: Record<string, string> = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" };

export default function Suit({ s, className = "" }: { s: string; className?: string }) {
  if (s === "N") return <>NT</>;
  return (
    <svg className={`sv s-${s} ${className}`} viewBox="0 0 100 120" role="img" aria-label={NAME[s]}>
      {SHAPES[s]}
    </svg>
  );
}
