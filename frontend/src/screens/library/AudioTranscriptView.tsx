import { forwardRef } from "react";
import { librarySourceUrl, type LibraryMaterialDetailRead } from "../../api/materials";

interface AudioTranscriptViewProps {
  material: LibraryMaterialDetailRead;
  onTimeUpdate: (seconds: number) => void;
}

/**
 * Локальный проигрыватель записи. Остаётся закреплённым при прокрутке
 * расшифровки: перемотка по сегменту бессмысленна, если плеер уехал вверх.
 */
export const AudioTranscriptView = forwardRef<HTMLAudioElement, AudioTranscriptViewProps>(
  function AudioTranscriptView({ material, onTimeUpdate }, ref) {
    return (
      <div className="audio-source">
        <div className="audio-player">
          <audio
            ref={ref}
            controls
            preload="metadata"
            src={librarySourceUrl(material.id)}
            onTimeUpdate={(event) => onTimeUpdate(event.currentTarget.currentTime)}
          >
            Ваш браузер не умеет проигрывать эту запись.
          </audio>
          <p className="audio-caption">{material.original_name}</p>
        </div>
        <p className="audio-note">
          Нажмите на сегмент расшифровки — запись перемотается к нему.
        </p>
      </div>
    );
  },
);
