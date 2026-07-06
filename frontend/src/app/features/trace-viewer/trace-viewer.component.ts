import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { TraceEntry } from '../../core/models';

@Component({
  selector: 'app-trace-viewer',
  imports: [JsonPipe],
  templateUrl: './trace-viewer.component.html',
  styleUrl: './trace-viewer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TraceViewerComponent {
  readonly trace = input<TraceEntry[]>([]);

  protected asText(entry: TraceEntry): string {
    return typeof entry['text'] === 'string' ? entry['text'] : '';
  }

  protected asName(entry: TraceEntry): string {
    return typeof entry['name'] === 'string' ? entry['name'] : '';
  }

  protected isError(entry: TraceEntry): boolean {
    return entry['is_error'] === true;
  }

  protected prettyInput(entry: TraceEntry): string {
    return JSON.stringify(entry['input'] ?? {}, null, 2);
  }

  protected prettyOutput(entry: TraceEntry): string {
    const output = entry['output'];
    if (typeof output === 'string') {
      try {
        return JSON.stringify(JSON.parse(output), null, 2);
      } catch {
        return output;
      }
    }
    return JSON.stringify(output ?? {}, null, 2);
  }
}
