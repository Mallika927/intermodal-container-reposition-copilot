import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { CycleStore } from '../../state/cycle.store';
import { NetworkHealthComponent } from '../network-health/network-health.component';
import { DecidePayload, RecommendationCardComponent } from '../recommendation-card/recommendation-card.component';
import { TraceViewerComponent } from '../trace-viewer/trace-viewer.component';

@Component({
  selector: 'app-dashboard',
  imports: [FormsModule, NetworkHealthComponent, RecommendationCardComponent, TraceViewerComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit {
  protected readonly store = inject(CycleStore);
  protected readonly seedValue = signal<number | null>(null);

  ngOnInit(): void {
    this.store.loadImbalance(this.seedValue() ?? undefined);
  }

  protected onRunCycle(): void {
    const seed = this.seedValue() ?? undefined;
    this.store.runCycle(seed);
    this.store.loadImbalance(seed);
  }

  protected onDecide(recId: string, payload: DecidePayload): void {
    this.store.decide(recId, payload.action, payload.modifiedUnits, payload.reason);
  }
}
