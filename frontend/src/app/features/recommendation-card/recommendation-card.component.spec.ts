import { TestBed } from '@angular/core/testing';

import { Recommendation } from '../../core/models';
import { RecommendationCardComponent } from './recommendation-card.component';

function buildRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: 'REC-2026-0704-001',
    created_ts: '2026-07-04T23:00:00Z',
    lane_id: 'LAX-ICTF_DEN-RG',
    equipment_type: '53FT-DRY',
    units: 100,
    priority: 'HIGH',
    execution_legs: [
      { train_id: 'ZLADE-01', units: 44, confidence: 1.0 },
      { train_id: 'ZLADE-02', units: 56, confidence: 0.75 },
    ],
    cost_usd: 24500,
    revenue_protected_usd: 185000,
    net_benefit_usd: 162900,
    reasoning_summary: 'DEN-RG is critically short of empties.',
    risks: ['56 units rely on projected train ZLADE-02.'],
    alternatives_considered: [
      {
        option_id: 'OPT-CHI-G4-KCS-IC-cover',
        summary: 'Move 87 units CHI-G4 -> KCS-IC',
        rejected_because: 'Lower net value.',
      },
    ],
    source_option_id: 'OPT-LAX-ICTF-DEN-RG-cover',
    status: 'pending',
    expires_at: '2026-07-05T11:00:00Z',
    ...overrides,
  };
}

function findButtonByText(root: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(root.querySelectorAll('button')).find(
    (candidate) => candidate.textContent?.trim() === text
  );
  if (!button) {
    throw new Error(`No button found with text "${text}"`);
  }
  return button as HTMLButtonElement;
}

describe('RecommendationCardComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RecommendationCardComponent],
    }).compileComponents();
  });

  it('emits an approved decision when Approve is clicked', () => {
    const fixture = TestBed.createComponent(RecommendationCardComponent);
    fixture.componentRef.setInput('recommendation', buildRecommendation());
    fixture.detectChanges();

    const emitted: unknown[] = [];
    fixture.componentInstance.decide.subscribe((event) => emitted.push(event));

    findButtonByText(fixture.nativeElement, 'Approve').click();

    expect(emitted).toEqual([{ action: 'approved' }]);
  });

  it('blocks rejection without a reason, then emits once one is provided', () => {
    const fixture = TestBed.createComponent(RecommendationCardComponent);
    fixture.componentRef.setInput('recommendation', buildRecommendation());
    fixture.detectChanges();

    const emitted: unknown[] = [];
    fixture.componentInstance.decide.subscribe((event) => emitted.push(event));

    findButtonByText(fixture.nativeElement, 'Reject').click();
    fixture.detectChanges();

    findButtonByText(fixture.nativeElement, 'Confirm rejection').click();
    fixture.detectChanges();

    expect(emitted).toEqual([]);
    const error = fixture.nativeElement.querySelector('.inline-form__error');
    expect(error?.textContent).toContain('A reason is required');

    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = 'Yard is over capacity this week.';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    findButtonByText(fixture.nativeElement, 'Confirm rejection').click();
    fixture.detectChanges();

    expect(emitted).toEqual([{ action: 'rejected', reason: 'Yard is over capacity this week.' }]);
  });

  it('shows a status chip instead of actions once decided', () => {
    const fixture = TestBed.createComponent(RecommendationCardComponent);
    fixture.componentRef.setInput('recommendation', buildRecommendation({ status: 'approved' }));
    fixture.detectChanges();

    const chip = fixture.nativeElement.querySelector('.status-chip');
    expect(chip?.textContent?.trim()).toBe('approved');
    expect(fixture.nativeElement.querySelector('.rec-card__actions')).toBeNull();
  });
});
