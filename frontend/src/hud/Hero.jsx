/**
 * hud/Hero.jsx - unboxed hero copy floating over the 3D scene.
 *
 * Anchored at the UPPER-LEFT thirds intersection (left vertical third,
 * centred on the upper horizontal third line), which keeps the entire
 * bottom third of the viewport free for widgets.
 *
 * Reveal: every line sits in an overflow-hidden mask and slides up when the
 * scroll sequence reaches Stage 3 (`<html data-stage="hero">`, set by
 * scene/choreography.js). Pure CSS - see `.mask` in hud.css.
 * Copy is placeholder - edit the constants below.
 */

const EYEBROW = 'Flights · Stays · Transfers · Landmarks';
/** One entry per masked headline line. */
const TITLE_LINES = ['Complete journeys,', 'effortlessly', 'choreographed'];
const TAGLINE =
  'Flights, stays, transfers, and local landmarks-tailored to your budget and pace in one seamless plan.';

/**
 * A single line-mask: the child slides up from behind its own clip box.
 * @param {{ index: number, children: React.ReactNode }} props
 *   index - stagger order (each step delays the slide by 90ms).
 * @returns {JSX.Element}
 */
function Mask({ index, children }) {
  return (
    <span className="mask" style={{ '--i': index }}>
      <span className="mask__inner">{children}</span>
    </span>
  );
}

/**
 * Hero eyebrow, display title and tagline. No buttons, inputs or boxes.
 * @returns {JSX.Element}
 */
export default function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <p className="hero__eyebrow">
        <Mask index={0}>{EYEBROW}</Mask>
      </p>
      <h1 className="hero__title" id="hero-title">
        {TITLE_LINES.map((line, i) => (
          <Mask key={line} index={i + 1}>
            {line}
            {i === TITLE_LINES.length - 1 && <span className="hero__accent">.</span>}
            {' '}
          </Mask>
        ))}
      </h1>
      <p className="hero__tagline">
        <Mask index={TITLE_LINES.length + 1}>{TAGLINE}</Mask>
      </p>
    </section>
  );
}
