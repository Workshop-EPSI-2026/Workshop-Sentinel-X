import { LEVEL_LABEL, type Level } from '../format';

// Une couleur d'état ne porte jamais le sens seule : forme distincte par niveau + libellé
export function StatusIcon({ level, size = 16 }: { level: Level; size?: number }) {
  const fill = `var(--status-${level})`;
  const dark = '#0b0b0b';
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="status-icon">
      {level === 'good' && (
        <>
          <circle cx="8" cy="8" r="7" fill={fill} />
          <path d="M4.6 8.3l2.2 2.2 4.6-4.9" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {level === 'warning' && (
        <>
          <path d="M8 1.2l7.2 13.1H.8z" fill={fill} strokeLinejoin="round" />
          <path d="M8 5.8v3.8M8 11.8v.2" stroke={dark} strokeWidth="1.8" strokeLinecap="round" />
        </>
      )}
      {level === 'serious' && (
        <>
          <rect x="2.6" y="2.6" width="10.8" height="10.8" rx="1.6" transform="rotate(45 8 8)" fill={fill} />
          <path d="M8 4.6v4.2M8 11v.2" stroke={dark} strokeWidth="1.8" strokeLinecap="round" />
        </>
      )}
      {level === 'critical' && (
        <>
          <path d="M5.1 1h5.8L15 5.1v5.8L10.9 15H5.1L1 10.9V5.1z" fill={fill} />
          <path d="M8 4.3v4.6M8 11.3v.2" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}

export function LevelTag({ level, label }: { level: Level; label?: string }) {
  return (
    <span className="level-tag">
      <StatusIcon level={level} />
      <span>{label ?? LEVEL_LABEL[level]}</span>
    </span>
  );
}
