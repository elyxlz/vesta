import { TrendingUpIcon, TrendingDownIcon } from "lucide-react"

export function RevenueCard() {
  return (
    <div className="rounded-2xl bg-secondary p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Total Revenue</span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <TrendingUpIcon className="size-3" />
          +12.5%
        </span>
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">$1,250.00</p>
      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
        Trending up this month <TrendingUpIcon className="size-3" />
      </div>
    </div>
  )
}

export function CustomersCard() {
  return (
    <div className="rounded-2xl bg-secondary p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">New Customers</span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <TrendingDownIcon className="size-3" />
          -20%
        </span>
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">1,234</p>
      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
        Down 20% this period <TrendingDownIcon className="size-3" />
      </div>
    </div>
  )
}

export function ActiveAccountsCard() {
  return (
    <div className="rounded-2xl bg-secondary p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Active Accounts</span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <TrendingUpIcon className="size-3" />
          +12.5%
        </span>
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">45,678</p>
      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
        Strong user retention <TrendingUpIcon className="size-3" />
      </div>
    </div>
  )
}

export function GrowthRateCard() {
  return (
    <div className="rounded-2xl bg-secondary p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Growth Rate</span>
        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
          <TrendingUpIcon className="size-3" />
          +4.5%
        </span>
      </div>
      <p className="mt-1 text-xl font-semibold tabular-nums">4.5%</p>
      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
        Steady performance increase <TrendingUpIcon className="size-3" />
      </div>
    </div>
  )
}
