// frontend/src/data/nseTop50.ts
// AIRP -- Top-50 NSE companies for the analysis-input autocomplete (T-058)
//
// A fixed, hand-maintained list of 50 large, well-known NSE-listed
// companies -- NOT a live market-cap ranking pulled from a screener API.
// There is no free, key-less "list all NSE tickers by market cap" API
// this project's stack already integrates with (see
// AIRP_Project_Overview_Updated.docx section 6's API list -- yFinance
// gives price/financials for a SYMBOL you already know, not a
// searchable directory of symbols), so a static dataset is the
// pragmatic, zero-cost way to satisfy "autocomplete works for top 50
// NSE stocks" today. If this list needs to move or reorder as market
// caps shift, edit this file directly -- there is deliberately no
// dynamic fetch/caching layer here to keep in sync.
//
// `ticker` is the exact Yahoo Finance symbol (with the .NS suffix)
// backend.services.analysis.resolve_company expects when a caller
// supplies AnalysisStartRequest.ticker directly (see that schema's
// docstring: "optional overrides for callers, e.g. a future
// autocomplete-driven frontend, that already know the exact Yahoo
// Finance symbol") -- selecting an option here sends `ticker` and
// `exchange` explicitly, skipping backend.services.analysis's
// name-resolution table entirely (which only covers ~15 names) rather
// than depending on it covering all 50.

export interface NseCompany {
  name: string;
  ticker: string;
  exchange: "NSE";
}

export const NSE_TOP_50: readonly NseCompany[] = [
  { name: "Reliance Industries", ticker: "RELIANCE.NS", exchange: "NSE" },
  { name: "Tata Consultancy Services", ticker: "TCS.NS", exchange: "NSE" },
  { name: "HDFC Bank", ticker: "HDFCBANK.NS", exchange: "NSE" },
  { name: "ICICI Bank", ticker: "ICICIBANK.NS", exchange: "NSE" },
  { name: "Infosys", ticker: "INFY.NS", exchange: "NSE" },
  { name: "State Bank of India", ticker: "SBIN.NS", exchange: "NSE" },
  { name: "Bharti Airtel", ticker: "BHARTIARTL.NS", exchange: "NSE" },
  { name: "ITC", ticker: "ITC.NS", exchange: "NSE" },
  { name: "Life Insurance Corporation of India", ticker: "LICI.NS", exchange: "NSE" },
  { name: "Hindustan Unilever", ticker: "HINDUNILVR.NS", exchange: "NSE" },
  { name: "Larsen & Toubro", ticker: "LT.NS", exchange: "NSE" },
  { name: "Bajaj Finance", ticker: "BAJFINANCE.NS", exchange: "NSE" },
  { name: "HCL Technologies", ticker: "HCLTECH.NS", exchange: "NSE" },
  { name: "Kotak Mahindra Bank", ticker: "KOTAKBANK.NS", exchange: "NSE" },
  { name: "Maruti Suzuki India", ticker: "MARUTI.NS", exchange: "NSE" },
  { name: "Sun Pharmaceutical Industries", ticker: "SUNPHARMA.NS", exchange: "NSE" },
  { name: "Axis Bank", ticker: "AXISBANK.NS", exchange: "NSE" },
  { name: "Titan Company", ticker: "TITAN.NS", exchange: "NSE" },
  { name: "Asian Paints", ticker: "ASIANPAINT.NS", exchange: "NSE" },
  { name: "NTPC", ticker: "NTPC.NS", exchange: "NSE" },
  { name: "UltraTech Cement", ticker: "ULTRACEMCO.NS", exchange: "NSE" },
  { name: "Adani Enterprises", ticker: "ADANIENT.NS", exchange: "NSE" },
  { name: "Adani Ports and Special Economic Zone", ticker: "ADANIPORTS.NS", exchange: "NSE" },
  { name: "Wipro", ticker: "WIPRO.NS", exchange: "NSE" },
  { name: "Oil and Natural Gas Corporation", ticker: "ONGC.NS", exchange: "NSE" },
  { name: "Nestle India", ticker: "NESTLEIND.NS", exchange: "NSE" },
  { name: "Power Grid Corporation of India", ticker: "POWERGRID.NS", exchange: "NSE" },
  { name: "Mahindra & Mahindra", ticker: "M&M.NS", exchange: "NSE" },
  { name: "JSW Steel", ticker: "JSWSTEEL.NS", exchange: "NSE" },
  { name: "Coal India", ticker: "COALINDIA.NS", exchange: "NSE" },
  { name: "Bajaj Finserv", ticker: "BAJAJFINSV.NS", exchange: "NSE" },
  { name: "Tata Motors", ticker: "TATAMOTORS.NS", exchange: "NSE" },
  { name: "IndusInd Bank", ticker: "INDUSINDBK.NS", exchange: "NSE" },
  { name: "Grasim Industries", ticker: "GRASIM.NS", exchange: "NSE" },
  { name: "Tech Mahindra", ticker: "TECHM.NS", exchange: "NSE" },
  { name: "Hindalco Industries", ticker: "HINDALCO.NS", exchange: "NSE" },
  { name: "Dr. Reddy's Laboratories", ticker: "DRREDDY.NS", exchange: "NSE" },
  { name: "Cipla", ticker: "CIPLA.NS", exchange: "NSE" },
  { name: "Eicher Motors", ticker: "EICHERMOT.NS", exchange: "NSE" },
  { name: "Britannia Industries", ticker: "BRITANNIA.NS", exchange: "NSE" },
  { name: "Divi's Laboratories", ticker: "DIVISLAB.NS", exchange: "NSE" },
  { name: "SBI Life Insurance", ticker: "SBILIFE.NS", exchange: "NSE" },
  { name: "HDFC Life Insurance", ticker: "HDFCLIFE.NS", exchange: "NSE" },
  { name: "Bajaj Auto", ticker: "BAJAJ-AUTO.NS", exchange: "NSE" },
  { name: "Tata Steel", ticker: "TATASTEEL.NS", exchange: "NSE" },
  { name: "Bharat Petroleum Corporation", ticker: "BPCL.NS", exchange: "NSE" },
  { name: "Apollo Hospitals Enterprise", ticker: "APOLLOHOSP.NS", exchange: "NSE" },
  { name: "Shree Cement", ticker: "SHREECEM.NS", exchange: "NSE" },
  { name: "Tata Consumer Products", ticker: "TATACONSUM.NS", exchange: "NSE" },
  { name: "Hero MotoCorp", ticker: "HEROMOTOCO.NS", exchange: "NSE" },
];
