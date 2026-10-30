// «Хлебные крошки»: где я нахожусь и как вернуться на уровень выше.

import { Link } from 'react-router-dom';

export interface Crumb {
  label: string;
  /** Нет ссылки — это текущая страница */
  to?: string;
}

export default function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Вы находитесь здесь" className="min-w-0 text-sm">
      <ol className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 text-muted">
        {items.map((c, i) => (
          <li key={i} className="flex min-w-0 items-center gap-1.5">
            {i > 0 && (
              <span aria-hidden className="text-line">
                /
              </span>
            )}
            {c.to ? (
              <Link to={c.to} className="font-semibold text-brand hover:underline">
                {c.label}
              </Link>
            ) : (
              <span aria-current="page" className="truncate text-ink">
                {c.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
