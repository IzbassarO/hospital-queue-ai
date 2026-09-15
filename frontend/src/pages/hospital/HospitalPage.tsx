import { useParams } from "react-router-dom";

import { useHospitalCard } from "../../api/queries";
import { ErrorState } from "../../components/ErrorState";
import { PageHeader } from "../../components/PageHeader";
import {
  BlockSkeleton,
  KpiSkeleton,
  Skeleton,
} from "../../components/Skeleton";
import { t } from "../../i18n";
import { CardHeader } from "./CardHeader";
import { Recommendations } from "./Recommendations";
import { ReferralsTable } from "./ReferralsTable";
import { SeriesChart } from "./SeriesChart";
import { WhyPanel } from "./WhyPanel";

/** Hospital × profile card: the core screen (status → chart → why → recommendations → referrals). */
export function HospitalPage() {
  const { org = "", profile = "" } = useParams();
  const card = useHospitalCard(org, profile);

  if (card.isError) {
    return (
      <>
        <PageHeader
          title={`${org} · ${profile}`}
          crumbs={[{ label: t.nav.overview, to: "/" }, { label: org }]}
        />
        <ErrorState error={card.error} onRetry={() => void card.refetch()} />
      </>
    );
  }

  // keyed by the route so paging / expanded rows reset when an alternative's card is opened
  return (
    <div key={`${org}:${profile}`} className="space-y-8">
      {card.data ? (
        <CardHeader status={card.data.status} />
      ) : (
        <div className="space-y-4">
          <Skeleton className="h-4 w-80" />
          <Skeleton className="h-8 w-2/3" />
          <KpiSkeleton count={6} />
        </div>
      )}
      {card.data ? (
        <SeriesChart card={card.data} />
      ) : (
        <BlockSkeleton height="h-[380px]" />
      )}
      {card.data ? (
        <WhyPanel factors={card.data.explanation_factors} />
      ) : (
        <BlockSkeleton height="h-64" />
      )}
      {/* independent requests: recommendations and referrals load in parallel with the card */}
      <Recommendations org={org} profile={profile} />
      <ReferralsTable org={org} profile={profile} />
    </div>
  );
}
