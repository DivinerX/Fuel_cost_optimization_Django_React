# Fuel Route Optimizer - Backend

Django REST Framework backend for the Fuel Route Optimizer application.



# 1. Why initial fuel level is required

In real fuel-planning systems, a vehicle almost never starts with an empty tank. Drivers may begin with a partially filled tank, a near-full tank, or sometimes only enough fuel to reach the first station. This affects the entire optimization process.

Including initial fuel level allows the algorithm to:

Avoid suggesting an unnecessary fuel stop early in the route.

Correctly handle situations where the first reachable station is very far away.

More accurately calculate fuel usage and remaining range from mile zero.

Produce results that are realistic for real fleet vehicles and logistics operations.

Without this parameter, the model would always assume a full tank and could never reflect real-world scenarios such as returning from a previous job, driving between cities, or mid-shift refuels. This is why initial fuel level is essential for proper route and cost optimization.



# 2. Greedy algorithm explanation

The greedy strategy focuses on minimizing cost at each step by making the best immediate decision based on fuel prices and reachable stations. It is simple, fast, and works well in many real situations.

Key behavior

Instead of always filling the tank completely, the greedy logic looks ahead to find cheaper stations within the vehicle’s reachable range. Once it detects a cheaper station down the road, it adjusts the fuel amount so the vehicle buys only the minimum gas needed to reach that cheaper station.

This creates more realistic fuel decisions:

Do not fill the tank at an expensive station.

Only add enough fuel to reach a cheaper station ahead.

When no cheaper station exists in range, fill enough to reach the cheapest available station in the window.

Repeat the process until reaching the destination.

Detailed steps

At any point on the route the vehicle has:

current fuel level

maximum range defined by tank capacity

distance to upcoming stations

Look at all reachable stations within current position plus available range.

Identify:

the first station that is cheaper than the current station, if one exists.

if none exist, identify the cheapest station in the reachable window.

Fuel strategy:

If a cheaper station exists ahead, buy just enough gallons to reach it.

If no cheaper station exists, buy enough fuel to safely reach the cheapest available option.

Refuel at that station and repeat.

Continue until the destination becomes reachable with the current fuel.

Benefits

Saves money by avoiding unnecessary full refuels at high priced stations.

Produces surprisingly good results with minimal logic.

Works well on real highway routes where price variation is significant.




# 3. Dijkstra algorithm explanation with discretization and graph structure

To guarantee the minimum possible fuel cost, the route is modeled as a shortest path problem and solved using Dijkstra. This requires converting the continuous road geometry into a discrete graph that captures possible fuel states at specific points along the route.

Discretization

The continuous polyline from the routing API must be reduced into a manageable set of nodes. This step is critical because it controls both accuracy and performance.

Key ideas:

Each node represents a specific position along the route.

Nodes are spaced by a discretization interval measured in miles.

Each node is assigned a cumulative distance from the start.

Fuel stations projected onto the route are also treated as nodes.

This creates a set of discrete positions where fuel decisions can be made.

Importance of the discretization interval

The interval chosen for discretization directly affects the quality of the optimal solution and the total runtime.

A smaller interval results in higher resolution, more nodes, and a more accurate graph.

A larger interval produces fewer nodes and faster computation but reduces precision.

During testing:

Interval 0.01 miles produced very precise results, almost identical to a continuous model, but increased runtime noticeably due to higher node count.

Interval 0.02 miles achieved a strong balance.
It is accurate enough to produce near perfect cost optimization while keeping the number of nodes manageable and the runtime well within acceptable limits.

This interval preserves optimality in practice while ensuring that Dijkstra can complete quickly, even for long routes.

Graph configuration

Once nodes are discretized:

Each node represents a position along the route.

Edges represent either driving or refueling actions.

Driving edges reduce fuel but have no monetary cost.

Refueling edges increase fuel and apply cost based on the station price.

This transforms the route into a classic weighted graph problem.

Using Dijkstra

Because all edge weights are non negative, Dijkstra is guaranteed to compute the globally optimal path through the fuel-state graph. It accounts for all combinations of:

where to stop,

how far to travel before each stop,

and how fuel level evolves along the route.

This method outperforms the greedy algorithm when there are complex price variations or when early local decisions affect later fuel opportunities.




# 4. API timing and performance explanation

The api/route endpoint currently responds in roughly 10 seconds. The key insight is that most of this time is spent waiting on the external routing provider rather than our own optimization logic.

External routing API cost

The system calls OpenRouteService to retrieve the optimized route geometry. This service is free and reliable but not fast for long routes. Typical response times are:

5 to 8 seconds for a full start to end route

Longer if the distance is large or the server is under load

This single call dominates the request lifecycle because it must complete before any fuel optimization can begin.

Internal optimization time

Once the route geometry is available, our system:

Parses the path and cumulative distances

Identifies candidate fuel stations along the corridor

Runs either the greedy approach or the Dijkstra based optimal algorithm

This part is efficient. The optimization typically completes in:

2 to 4 seconds, depending on route length and the number of stations in range

### The internal logic is not the bottleneck. Most of the time is spent waiting for the routing API.

Potential improvement with faster routing providers

If we integrate a faster routing or map service, such as Mapbox Directions API, the total response time can be reduced significantly. Mapbox typically returns long routes in:

0.5 to 1.5 seconds on average

Using a faster routing provider would have the following impact:

Immediate reduction of the 5 to 8 second wait time

Total request time could drop to around 3 to 5 seconds

The optimization time becomes the main cost instead of external API delays

The system feels significantly more responsive for end users

Summary

Current total: ~10 seconds

Majority of time: OpenRouteService (5 to 8 seconds)

Our logic: only 2 to 4 seconds

Upgrading routing provider (Mapbox) can reduce total to ~3 to 5 seconds



## API Endpoints

- `POST /api/route/`
  - Plans a full route (start → end) and returns optimized fuel stops, costs, and route geometry.
  - Request body example:
    ```json
    {
      "start_location": "New York, NY",
      "end_location": "Los Angeles, CA",
      "algorithm": "dijkstra",
      "initial_fuel_gallons": 20
    }
    ```
  - Response includes the optimized stop list plus diagnostic data (total fuel purchased, cost, etc.).
- `GET /api/route/autocomplete/?q=<query>`
  - Returns up to five U.S.-based geocoding suggestions for the provided text query.
  - Example: `/api/route/autocomplete/?q=Seattle`
