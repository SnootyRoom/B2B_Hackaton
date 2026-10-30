// Знак продукта — красная кедровая шишка (Томск, Сибирь). Белые линии — чешуйки.

export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className="shrink-0">
      {/* хвостик */}
      <path d="M12 1.2v2.4" stroke="var(--color-brand-dark)" strokeWidth="1.6" strokeLinecap="round" />
      {/* тело шишки */}
      <path
        d="M12 3c4.6 3.3 6.8 8 6 12.6C17.3 19.7 14.9 22.6 12 22.6S6.7 19.7 6 15.6C5.2 11 7.4 6.3 12 3Z"
        fill="var(--color-brand)"
      />
      {/* чешуйки */}
      <g fill="none" stroke="#fff" strokeOpacity="0.7" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8.6 8.6 12 11l3.4-2.4" />
        <path d="M7.3 12.8 12 15.9l4.7-3.1" />
        <path d="M8 17.2l4 2.6 4-2.6" />
      </g>
    </svg>
  );
}
