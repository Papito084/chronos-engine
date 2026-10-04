import React, { useState, useEffect } from 'react';

interface OrderFormProps {
  symbol: string;
  selectedPrice?: number | null;
  onOrderPlaced?: () => void;
}

export const OrderForm: React.FC<OrderFormProps> = ({
  symbol,
  selectedPrice,
  onOrderPlaced,
}) => {
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [orderType, setOrderType] = useState<'LIMIT' | 'MARKET'>('LIMIT');
  const [price, setPrice] = useState<string>('65000.00');
  const [quantity, setQuantity] = useState<string>('0.10');
  const [tif, setTif] = useState<'GTC' | 'IOC' | 'FOK'>('GTC');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<{
    type: 'success' | 'error';
    text: string;
  } | null>(null);

  // Update price when selectedPrice changes from OrderBook click
  useEffect(() => {
    if (selectedPrice != null && selectedPrice > 0) {
      setPrice(selectedPrice.toFixed(2));
    }
  }, [selectedPrice]);

  const numPrice = parseFloat(price) || 0;
  const numQty = parseFloat(quantity) || 0;
  const totalValue = orderType === 'LIMIT' ? numPrice * numQty : 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (numQty <= 0) {
      setStatusMessage({ type: 'error', text: 'Quantity must be greater than 0' });
      return;
    }
    if (orderType === 'LIMIT' && numPrice <= 0) {
      setStatusMessage({ type: 'error', text: 'Limit price must be greater than 0' });
      return;
    }

    setIsSubmitting(true);
    setStatusMessage(null);

    const payload = {
      symbol,
      side,
      order_type: orderType,
      price: orderType === 'LIMIT' ? numPrice : 0,
      quantity: numQty,
      time_in_force: orderType === 'MARKET' ? 'IOC' : tif,
    };

    try {
      const res = await fetch('/api/v1/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok) {
        const errorDetail = typeof data.detail === 'object' ? data.detail.message || data.detail.reason : data.detail;
        throw new Error(errorDetail || 'Order submission failed');
      }

      setStatusMessage({
        type: 'success',
        text: `Order ${data.status}: ID ${data.order_id.slice(0, 10)}... (${data.trades.length} fills)`,
      });

      if (onOrderPlaced) onOrderPlaced();
    } catch (err: any) {
      setStatusMessage({
        type: 'error',
        text: err.message || 'Network error sending order',
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const quickQuantities = [0.01, 0.05, 0.1, 0.5, 1.0];

  return (
    <div className="flex flex-col bg-[#12161c] border border-[#1e2329] rounded p-3 text-xs select-none">
      {/* Side Selector (Buy / Sell) */}
      <div className="grid grid-cols-2 gap-1 p-0.5 bg-[#0b0e11] rounded mb-3 border border-[#1e2329]">
        <button
          type="button"
          onClick={() => setSide('BUY')}
          className={`py-1.5 font-bold rounded text-xs transition-colors duration-100 ${
            side === 'BUY'
              ? 'bg-[#0ecb81] text-black shadow'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          Buy {symbol.split('-')[0]}
        </button>
        <button
          type="button"
          onClick={() => setSide('SELL')}
          className={`py-1.5 font-bold rounded text-xs transition-colors duration-100 ${
            side === 'SELL'
              ? 'bg-[#f6465d] text-white shadow'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          Sell {symbol.split('-')[0]}
        </button>
      </div>

      {/* Order Type Selector */}
      <div className="flex gap-4 mb-3 text-xs border-b border-[#1e2329] pb-2">
        <button
          type="button"
          onClick={() => setOrderType('LIMIT')}
          className={`pb-0.5 font-medium transition-colors ${
            orderType === 'LIMIT'
              ? 'text-white border-b-2 border-yellow-400'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Limit
        </button>
        <button
          type="button"
          onClick={() => setOrderType('MARKET')}
          className={`pb-0.5 font-medium transition-colors ${
            orderType === 'MARKET'
              ? 'text-white border-b-2 border-yellow-400'
              : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          Market
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2.5">
        {/* Price Input (if Limit) */}
        {orderType === 'LIMIT' ? (
          <div>
            <label className="block text-[10px] text-gray-400 mb-1">Price (USDT)</label>
            <div className="relative flex items-center">
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="w-full bg-[#1e2329]/60 border border-[#2b313a] rounded px-3 py-1.5 text-white font-mono text-xs focus:outline-none focus:border-yellow-400"
                placeholder="0.00"
                required
              />
              <span className="absolute right-3 text-[10px] text-gray-500">USDT</span>
            </div>
          </div>
        ) : (
          <div>
            <label className="block text-[10px] text-gray-400 mb-1">Price</label>
            <div className="w-full bg-[#1e2329]/30 border border-[#2b313a]/50 rounded px-3 py-1.5 text-gray-500 font-mono text-xs">
              Market (Best Execution)
            </div>
          </div>
        )}

        {/* Quantity Input */}
        <div>
          <label className="block text-[10px] text-gray-400 mb-1">Quantity ({symbol.split('-')[0]})</label>
          <div className="relative flex items-center">
            <input
              type="number"
              step="0.0001"
              min="0.0001"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className="w-full bg-[#1e2329]/60 border border-[#2b313a] rounded px-3 py-1.5 text-white font-mono text-xs focus:outline-none focus:border-yellow-400"
              placeholder="0.00"
              required
            />
            <span className="absolute right-3 text-[10px] text-gray-500">
              {symbol.split('-')[0]}
            </span>
          </div>
        </div>

        {/* Quick Quantity Buttons */}
        <div className="grid grid-cols-5 gap-1">
          {quickQuantities.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setQuantity(q.toString())}
              className="py-1 bg-[#1e2329] hover:bg-[#2b313a] text-gray-400 hover:text-white rounded text-[10px] font-mono transition-colors"
            >
              {q}
            </button>
          ))}
        </div>

        {/* Time In Force (if Limit) */}
        {orderType === 'LIMIT' && (
          <div>
            <label className="block text-[10px] text-gray-400 mb-1">Time In Force</label>
            <div className="grid grid-cols-3 gap-1">
              {(['GTC', 'IOC', 'FOK'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTif(t)}
                  className={`py-1 rounded text-[10px] font-medium border ${
                    tif === t
                      ? 'border-yellow-400/80 bg-yellow-400/10 text-yellow-400'
                      : 'border-[#2b313a] bg-[#1e2329]/50 text-gray-400 hover:text-gray-300'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Total Value Estimation */}
        {orderType === 'LIMIT' && (
          <div className="flex justify-between items-center text-[11px] text-gray-400 pt-1 border-t border-[#1e2329]">
            <span>Order Value:</span>
            <span className="font-mono text-gray-200">
              {totalValue.toLocaleString('en-US', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}{' '}
              USDT
            </span>
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isSubmitting}
          className={`w-full py-2.5 mt-1 rounded font-bold text-xs uppercase tracking-wider transition-all duration-100 ${
            side === 'BUY'
              ? 'bg-[#0ecb81] hover:bg-[#0cb874] text-black active:scale-[0.99]'
              : 'bg-[#f6465d] hover:bg-[#e03d52] text-white active:scale-[0.99]'
          } ${isSubmitting ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          {isSubmitting
            ? 'Transmitting...'
            : `${side} ${symbol.split('-')[0]}`}
        </button>

        {/* Status Message */}
        {statusMessage && (
          <div
            className={`p-2 rounded text-[11px] font-mono border ${
              statusMessage.type === 'success'
                ? 'bg-[#0ecb81]/10 border-[#0ecb81]/40 text-[#0ecb81]'
                : 'bg-[#f6465d]/10 border-[#f6465d]/40 text-[#f6465d]'
            }`}
          >
            {statusMessage.text}
          </div>
        )}
      </form>
    </div>
  );
};
