import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { ImbalanceEntry } from '../../core/models';

@Component({
  selector: 'app-network-health',
  templateUrl: './network-health.component.html',
  styleUrl: './network-health.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NetworkHealthComponent {
  readonly entries = input<ImbalanceEntry[]>([]);

  protected readonly sortedEntries = computed(() =>
    [...this.entries()].sort((a, b) => a.projected_balance - b.projected_balance)
  );

  protected signedBalance(balance: number): string {
    return balance > 0 ? `+${balance}` : `${balance}`;
  }
}
