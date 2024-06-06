import json,config
import time
from flask import Flask,request,render_template,render_template_string
from binance.client import Client
from binance.enums import *
from binance.helpers import round_step_size
import requests
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
app = Flask(__name__)
client = Client(config.API_KEY,config.API_SECRET,tld = "com",testnet = True)

takeProfitFactor=15.5/100
stopLossFactor=9/100



def stopLoss(symbol,side,limitPrice,stopPrice):
    qty = abs(float(client.futures_position_information(symbol = symbol)[0]['positionAmt']))
    try:
        order = client.futures_create_order(symbol=symbol,side=side, type=FUTURE_ORDER_TYPE_STOP, quantity=qty,price=limitPrice,stopPrice=stopPrice,stopLimitTimeInForce='GTC')
    except Exception as e:
        print("an exception occured - {}".format(e))
        return False
    return True    

def takeProfit(symbol,side,limitPrice,stopPrice):
    qty = abs(float(client.futures_position_information(symbol = symbol)[0]['positionAmt']))
    try:
        order = client.futures_create_order(symbol=symbol,side=side, type=FUTURE_ORDER_TYPE_TAKE_PROFIT, quantity=qty,price=limitPrice,stopPrice=stopPrice,stopLimitTimeInForce='GTC')
    except Exception as e:
        print("an exception occured - {}".format(e))
        return False
    return True  



def order(side, quantity, symbol,price,order_type,timeInForce):
    position = open_position()
    if position == None:
        print("quantity",quantity)
        try:
            client.futures_change_leverage(symbol=symbol, leverage = 1)
            order = client.futures_create_order(symbol=symbol, side=side, type=ORDER_TYPE_MARKET, quantity=quantity)
            #order = client.futures_create_order(symbol=symbol, timeInForce=timeInForce, side=side, type=order_type, quantity=quantity,price=price)
        except Exception as e:
            print("an exception occured - {}".format(e))
            return False
        return True
    else:
        if position[0] != symbol :
            print("Already open position in another coin")
            return False
        elif position[0] == symbol and (side == "SELL" and float(position[1]) < 0 ):
            print("Position in this coin is already short")
            return False
        elif position[0] == symbol and (side == "BUY" and float(position[1]) > 0 ):
            print("Position in this coin is already long")
            return False
        else:
            try:
                client.futures_change_leverage(symbol=symbol, leverage = 1)
                qty = abs(float(client.futures_position_information(symbol = symbol)[0]['positionAmt']))
                print("qty",qty)
                order = client.futures_create_order(symbol=symbol, side=side, type=order_type, quantity=qty)
            except Exception as error:
                print("an exception occured - {}".format(error))
                return False
            return True







def open_position():
    open_positions = []
    account_info = client.futures_account()  # Replace 'client' with your trading client or API object
    for position in account_info['positions']:
        if float(position['positionAmt']) != 0:
            open_positions.append(position)
    if not open_positions:
        return None
    else:
        return [open_positions[0]['symbol'],open_positions[0]['positionAmt']]


def get_latest_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
    response = requests.get(url)
    data = response.json()
    latest_price = data["lastPrice"]
    return latest_price


def getRoundedByTick(symbol,price):
    tickDict = {
        "GALAUSDT": 0.0001,
        "LINKUSDT": 0.001,
        "INJUSDT": 0.01,
        "ATOMUSDT": 0.001,
        "DOTUSDT": 0.001,
        "ARBUSDT": 0.0001,
        "BTCUSDT": 0.001
    }
    tickSize = tickDict[symbol] 

    limitTakeProfitPrice = round_step_size(takeProfitFactor*price+price,tickSize)
    takeProfitPrice = round_step_size((takeProfitFactor+tickSize)*price+price,tickSize)
    limitStopLossPrice = round_step_size(price-takeProfitFactor*price,tickSize)
    stopLossPrice = round_step_size(price - (stopLossFactor+tickSize)*price ,tickSize)
    
    limitTakeProfitPrice=round(limitTakeProfitPrice,1)
    takeProfitPrice=round(takeProfitPrice,1)
    limitStopLossPrice=round(limitStopLossPrice,1)
    stopLossPrice=round(stopLossPrice,1)
    print("price:",price)
    print("takeprofitPrice", takeProfitPrice)
    print("limitTakeProfitPrice", limitTakeProfitPrice)
    print("stopLossPricece",stopLossPrice)

    return [limitTakeProfitPrice,takeProfitPrice,limitStopLossPrice,stopLossPrice]

def close_all_positions_and_orders():

    # Fetch all open positions
    account_info = client.futures_account()
    positions = account_info['positions']

    # Cancel all open orders
    open_orders = client.futures_get_open_orders()
    for order in open_orders:
        symbol = order['symbol']
        order_id = order['orderId']

        # Cancel the open order
        client.futures_cancel_order(
            symbol=symbol,
            orderId=order_id
        )

        print(f"Order cancelled: {symbol} - Order ID: {order_id}")

    # Iterate over each position and place sell orders
    for position in positions:
        symbol = position['symbol']
        quantity = float(position['positionAmt'])

        if quantity != 0:
            # Place a market sell order to close the position
            client.futures_create_order(
                symbol=symbol,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=abs(quantity)
            )

            print(f"Position closed: {symbol}")

@app.route('/webhook',methods=['POST'])
def webhook():
    #print(request.data)
    data = json.loads(request.data)
    if data['passphrase'] != config.WEBHOOK_PASSPHRASE:
        return{
            "code":"error",
            "message": "Invalid Passphrase"
        }
    

    order_type = ORDER_TYPE_LIMIT
    timeInForce = TIME_IN_FORCE_GTC
    ticker = data['ticker'].upper()
    side = data['strategy']['order_action'].upper()
    price = float(get_latest_price(ticker))
    quantity = (float(client.futures_account()['availableBalance'])*0.97) / price
    quantity = round(quantity,2)

    tp_sl = getRoundedByTick(ticker,price)
    reverseSide = "BUY" if side=="SELL" else "SELL"
    print(tp_sl)
    print(ticker)
    
    order_response = order(side, quantity,ticker,price,order_type,timeInForce)
    time.sleep(4)
    stopLoss(ticker,reverseSide,tp_sl[2],tp_sl[3])
    takeProfit(ticker,reverseSide,tp_sl[0],tp_sl[1])

    
    if order_response and stopLoss and takeProfit:
        return {
            "code":"success",
            "message":"order executed"
        }
    else:
        print("order failed")

        return{
            "code":"error",
            "message":"order failed"
        }



@app.route('/',methods=['POST'])
def clearPositions():
    while True:
        # Get the current time
        current_time = datetime.now(ZoneInfo("Europe/Athens"))
        #if (((current_time.hour >= 13 and current_time.minute >= 10) and current_time.hour <= 14) or ((current_time.hour >= 0 and current_time.minute >= 10) and current_time.hour <= 1)):
        if (((current_time.hour >= 13 and current_time.minute >= 10) and current_time.hour <= 15) or ((current_time.hour >= 0 and current_time.minute >= 10) and current_time.hour <= 1)):
            close_all_positions_and_orders()
        # Wait for 30 minutes
        #time.sleep(30*60)
        print("waiting")
        time.sleep(30)


if __name__ == '__main__':
    app.run(app.run(debug=True))


    

# @app.route('/')
# def results():
#     ####### BALANCE AND OPEN POSITIONS #######
#     balance = client.futures_account()['availableBalance']
#     position = open_position() if open_position() else "No Position"
    
#     ####### CRYPTO POSITIONS #######
#     crypto_dict = {}
#     crypto = ["GALAUSDT","LINKUSDT","DOTUSDT","ARBUSDT","ATOMUSDT","INJUSDT"]
#     for i in range(len(crypto)):
#         crypto_info = client.futures_position_information(symbol = crypto[i])
#         symbol = crypto_info[0]['symbol']
#         posAmt = crypto_info[0]['positionAmt']
#         crypto_dict[symbol] = posAmt
#     print(crypto_dict)
#     return render_template('index.html',crypto_dict=crypto_dict,position=position,balance=balance)
