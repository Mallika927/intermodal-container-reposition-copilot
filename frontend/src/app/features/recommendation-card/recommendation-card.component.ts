import { CurrencyPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { DecisionAction, Recommendation } from '../../core/models';

export interface DecidePayload {
  action: DecisionAction;
  modifiedUnits?: number;
  reason?: string;
}

@Component({
  selector: 'app-recommendation-card',
  imports: [CurrencyPipe, FormsModule],
  templateUrl: './recommendation-card.component.html',
  styleUrl: './recommendation-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RecommendationCardComponent {
  readonly recommendation = input.required<Recommendation>();
  readonly decisionInFlight = input<boolean>(false);

  readonly decide = output<DecidePayload>();

  protected readonly expanded = signal(false);
  protected readonly modifyOpen = signal(false);
  protected readonly rejectOpen = signal(false);
  protected readonly modifiedUnitsValue = signal<number | null>(null);
  protected readonly reasonValue = signal('');
  protected readonly modifyError = signal<string | null>(null);
  protected readonly rejectError = signal<string | null>(null);

  protected toggleExpanded(): void {
    this.expanded.update((value) => !value);
  }

  protected approve(): void {
    this.decide.emit({ action: 'approved' });
  }

  protected openModify(): void {
    this.rejectOpen.set(false);
    this.modifyError.set(null);
    this.modifiedUnitsValue.set(this.recommendation().units);
    this.modifyOpen.set(true);
  }

  protected cancelModify(): void {
    this.modifyOpen.set(false);
    this.modifyError.set(null);
  }

  protected confirmModify(): void {
    const units = this.modifiedUnitsValue();
    if (units == null || units <= 0) {
      this.modifyError.set('Enter a unit count greater than zero.');
      return;
    }
    this.decide.emit({ action: 'modified', modifiedUnits: units });
    this.modifyOpen.set(false);
  }

  protected openReject(): void {
    this.modifyOpen.set(false);
    this.rejectError.set(null);
    this.reasonValue.set('');
    this.rejectOpen.set(true);
  }

  protected cancelReject(): void {
    this.rejectOpen.set(false);
    this.rejectError.set(null);
  }

  protected confirmReject(): void {
    const reason = this.reasonValue().trim();
    if (!reason) {
      this.rejectError.set('A reason is required to reject a recommendation.');
      return;
    }
    this.decide.emit({ action: 'rejected', reason });
    this.rejectOpen.set(false);
  }

  protected confidenceLabel(confidence: number): string {
    return confidence >= 1 ? 'confirmed' : `projected (${Math.round(confidence * 100)}%)`;
  }
}
