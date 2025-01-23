import os
import requests
import json
from datetime import datetime
import time
import pandas as pd
import yfinance as yf
from twilio.rest import Client
from typing import List, Dict, Any

class StockScanner:
    def __init__(self):
        self.api_key = os.getenv('FMP_API_KEY')
        self.api_calls = 0
        self.max_daily_calls = 250
        
    def check_api_quota(self) -> bool:
        try:
            url = f"https://financialmodelingprep.com/api/v3/quota?apikey={self.api_key}"
            response = requests.get(url)
            data = response.json()
            
            if 'remainingCalls' in data:
                remaining_calls = data['remainingCalls']
                print(f"Remaining API calls: {remaining_calls}")
                return remaining_calls > 5
            return False
            
        except Exception as e:
            print(f"Error checking API quota: {str(e)}")
            return False

    def _make_api_call(self, url: str, retries: int = 3) -> dict:
        for i in range(retries):
            try:
                self.api_calls += 1
                if self.api_calls > self.max_daily_calls:
                    raise Exception("Daily API call limit reached")
                
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                
                time.sleep(0.2 * (i + 1))
                return response.json()
                
            except requests.exceptions.RequestException as e:
                if i == retries - 1:
                    raise Exception(f"API call failed after {retries} retries: {str(e)}")
                time.sleep(1 * (i + 1))
        
        raise Exception("API call failed with unknown error")

    def get_initial_stocks(self) -> List[Dict[str, Any]]:
        try:
            quote_url = f"https://financialmodelingprep.com/api/v3/quotes/nasdaq?apikey={self.api_key}"
            quotes = self._make_api_call(quote_url)
            
            stocks_info = []
            for quote in quotes:
                try:
                    symbol = quote.get('symbol', '')
                    current_price = quote.get('price', 0)
                    year_low = quote.get('yearLow', 0)
                    
                    if current_price and year_low and current_price <= (year_low * 1.02):
                        stocks_info.append({
                            'symbol': symbol,
                            'price': current_price,
                            'yearLow': year_low
                        })
                
                except (ValueError, TypeError) as e:
                    continue
                    
            return stocks_info
            
        except Exception as e:
            print(f"Error fetching initial stock data: {str(e)}")
            return []

    def enrich_stock_data(self, stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        enriched_stocks = []
        total_stocks = len(stocks)
        
        print(f"\nEnriching data for {total_stocks} stocks...")
        
        for i, stock in enumerate(stocks, 1):
            try:
                print(f"\rProcessing: {i}/{total_stocks} ({(i/total_stocks*100):.1f}%)", end="")
                
                yf_ticker = yf.Ticker(stock['symbol'])
                info = yf_ticker.info
                
                market_cap = info.get('marketCap', 0)
                if not (10000000 <= market_cap <= 300000000):
                    continue
                
                market_cap_str = f"${market_cap/1e6:.1f}M"
                
                stock_info = {
                    'Symbol': stock['symbol'],
                    'Company Name': info.get('longName', 'N/A'),
                    'Current Price': round(stock['price'], 2),
                    '52-Week Low': round(stock['yearLow'], 2),
                    'Distance from Low': f"{round((stock['price']/stock['yearLow'] - 1) * 100, 2)}%",
                    'Market Cap': market_cap_str,
                    'Industry': info.get('industry', 'N/A'),
                    'Sector': info.get('sector', 'N/A'),
                    'Volume': info.get('volume', 0),
                    'Description': info.get('longBusinessSummary', 'N/A')[:200] + '...'
                }
                
                enriched_stocks.append(stock_info)
                time.sleep(0.1)
                
            except Exception as e:
                print(f"\nError processing {stock['symbol']}: {str(e)}")
                continue
        
        print("\nData enrichment complete!")
        return enriched_stocks

    def scan_stocks(self) -> List[Dict[str, Any]]:
        initial_stocks = self.get_initial_stocks()
        print(f"Found {len(initial_stocks)} stocks at 52-week lows")
        
        enriched_stocks = self.enrich_stock_data(initial_stocks)
        return enriched_stocks

def send_whatsapp(stocks_data: List[Dict[str, Any]], account_sid: str, auth_token: str, 
                 from_number: str, to_number: str, api_calls: int) -> None:
    MAX_MESSAGE_LENGTH = 1600
    
    message_body = "🚨 *Small Cap Stocks at 52-Week Lows* 🚨\n\n"
    
    for stock in stocks_data:
        message_body += f"*{stock['Symbol']} - {stock['Company Name']}*\n"
        message_body += f"💵 Price: ${stock['Current Price']}\n"
        message_body += f"📊 From Low: {stock['Distance from Low']}\n"
        message_body += f"🏢 Industry: {stock['Industry']}\n"
        message_body += f"💰 Market Cap: {stock['Market Cap']}\n\n"
    
    message_body += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    message_body += f"FMP API Calls Used: {api_calls}"
    
    if len(message_body) > MAX_MESSAGE_LENGTH:
        message_body = message_body[:MAX_MESSAGE_LENGTH-100] + "\n\n(Message truncated due to length)"
    
    try:
        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        message = client.messages.create(
            body=message_body,
            from_=os.getenv('TWILIO_FROM_NUMBER'),
            to=os.getenv('TWILIO_TO_NUMBER')
        )
        print(f"WhatsApp message sent successfully! SID: {message.sid}")
        
    except Exception as e:
        print(f"Error sending WhatsApp message: {str(e)}")

def main():
    scanner = StockScanner()
    
    if not scanner.check_api_quota():
        print("Insufficient API calls remaining")
        return
    
    try:
        stocks_at_low = scanner.scan_stocks()
        if stocks_at_low:
            send_whatsapp(
                stocks_at_low,
                os.getenv('TWILIO_ACCOUNT_SID'),
                os.getenv('TWILIO_AUTH_TOKEN'),
                os.getenv('TWILIO_FROM_NUMBER'),
                os.getenv('TWILIO_TO_NUMBER'),
                scanner.api_calls
            )
            print(f'Successfully processed {len(stocks_at_low)} stocks')
        else:
            print('No small cap stocks found at 52-week lows.')
    except Exception as e:
        print(f'Error running scanner: {str(e)}')

if __name__ == "__main__":
    main()