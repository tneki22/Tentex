import { ArrowLeft, Globe } from "lucide-react";
import { Link } from "react-router";
import { PageHead } from "../../components/ui";
import { SourceSearchChat } from "../workspace/chat/SourceSearchChat";

/** Отдельная библиотечная поверхность общего поискового чата. */
export function LibrarySearch() {
  return (
    <div className="screen library-search-page">
      <PageHead
        placement="topbar"
        title="Поиск материалов"
        lead="Поиск в интернете по вашим запросам, без контекста проектов и Библиотеки."
        actions={<Link className="text-button" to="/library"><ArrowLeft size={15} />Библиотека</Link>}
      />
      <section className="library-search-surface" aria-label="Поиск в интернете для Библиотеки">
        <div className="library-search-heading"><Globe size={16} /><strong>Поиск в интернете</strong></div>
        <SourceSearchChat projectId={null} nodes={[]} variant="library" />
      </section>
    </div>
  );
}
