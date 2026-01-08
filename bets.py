import requests
import json


def get_politics_bets(limit=10):
    # Polymarket Gamma API endpoint for events
    # We fetch more than 'limit' (e.g. 20) to ensure we find enough politics markets after filtering
    url = "https://gamma-api.polymarket.com/events"

    params = {
        "limit": 20,  # Fetch top 20 active events
        "active": "true",  # Only live markets
        "closed": "false",  # No resolved markets
        "order": "volume",  # Sort by highest volume
        "ascending": "false"  # Descending order
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        found_bets = 0
        print(f"\n--- 🦅 Top {limit} Political Bets on Polymarket ---\n")

        for event in data:
            if found_bets >= limit:
                break

            # 1. Filter for 'Politics' tag
            # The API returns a list of tags for each event. We check if any tag name contains "Politics"
            tags = [t.get('slug', '').lower() for t in event.get('tags', [])]
            if 'politics' not in tags:
                continue

            # 2. Extract Market Data
            markets = event.get('markets', [])
            if not markets:
                continue

            # Usually the first market in the event is the main binary (Yes/No) bet
            main_market = markets[0]
            title = event.get('title')
            volume = int(float(event.get('volume', 0)))

            # 3. Format Outcomes & Prices
            outcomes = json.loads(main_market.get('outcomes', '[]'))
            prices = json.loads(main_market.get('outcomePrices', '[]'))

            print(f"Bet: {title}")
            print(f"Volume: ${volume:,.0f}")

            # Print the prices (odds)
            for outcome, price in zip(outcomes, prices):
                # Convert string price "0.65" to percentage "65.0%"
                try:
                    p_val = float(price) * 100
                    print(f"  {outcome}: {p_val:.1f}%")
                except (ValueError, TypeError):
                    print(f"  {outcome}: N/A")

            print("-" * 40)
            found_bets += 1

        if found_bets == 0:
            print("No politics markets found in the top volume list.")

    except Exception as e:
        print(f"Error fetching data: {e}")


if __name__ == "__main__":
    get_politics_bets(10)