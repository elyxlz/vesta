"use client"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { TrendingUpIcon, TrendingDownIcon } from "lucide-react"

export function RevenueCard() {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>Total Revenue</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          $1,250.00
        </CardTitle>
        <CardAction>
          <Badge variant="outline">
            <TrendingUpIcon />
            +12.5%
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1.5 text-sm">
        <div className="line-clamp-1 flex gap-2 font-medium">
          Trending up this month <TrendingUpIcon className="size-4" />
        </div>
        <div className="text-muted-foreground">
          Visitors for the last 6 months
        </div>
      </CardFooter>
    </Card>
  )
}

export function CustomersCard() {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>New Customers</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          1,234
        </CardTitle>
        <CardAction>
          <Badge variant="outline">
            <TrendingDownIcon />
            -20%
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1.5 text-sm">
        <div className="line-clamp-1 flex gap-2 font-medium">
          Down 20% this period <TrendingDownIcon className="size-4" />
        </div>
        <div className="text-muted-foreground">
          Acquisition needs attention
        </div>
      </CardFooter>
    </Card>
  )
}

export function ActiveAccountsCard() {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>Active Accounts</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          45,678
        </CardTitle>
        <CardAction>
          <Badge variant="outline">
            <TrendingUpIcon />
            +12.5%
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1.5 text-sm">
        <div className="line-clamp-1 flex gap-2 font-medium">
          Strong user retention <TrendingUpIcon className="size-4" />
        </div>
        <div className="text-muted-foreground">Engagement exceed targets</div>
      </CardFooter>
    </Card>
  )
}

export function GrowthRateCard() {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription>Growth Rate</CardDescription>
        <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
          4.5%
        </CardTitle>
        <CardAction>
          <Badge variant="outline">
            <TrendingUpIcon />
            +4.5%
          </Badge>
        </CardAction>
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1.5 text-sm">
        <div className="line-clamp-1 flex gap-2 font-medium">
          Steady performance increase <TrendingUpIcon className="size-4" />
        </div>
        <div className="text-muted-foreground">Meets growth projections</div>
      </CardFooter>
    </Card>
  )
}
