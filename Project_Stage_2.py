import json
from flask import Flask, jsonify, request, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from flask_cors import CORS
import requests

# Initialize Flask app and configure SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mtg_deckbuilder.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define Models
class Card(db.Model):
    __tablename__ = 'cards'
    card_name = db.Column(db.String, primary_key=True)
    mana_cost = db.Column(db.String)
    text = db.Column(db.String)
    card_type = db.Column(db.String)
    power = db.Column(db.Integer, nullable=True)
    toughness = db.Column(db.Integer, nullable=True)
    loyalty = db.Column(db.Integer, nullable=True)
    defense = db.Column(db.Integer, nullable=True)
    image_url = db.Column(db.String, nullable=True)
    art_url = db.Column(db.String, nullable=True)

    __table_args__ = (
        db.Index('ix_card_card_name', 'card_name'),
        db.Index('ix_card_mana_cost', 'mana_cost'),
    )

class User(db.Model):
    __tablename__ = 'users'
    username = db.Column(db.String, primary_key=True)
    password = db.Column(db.String)  # Hash passwords in production!

class Deck(db.Model):
    __tablename__ = 'decks'
    deck_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    deck_name = db.Column(db.String)
    format = db.Column(db.String, db.ForeignKey('formats.format_name'))
    commander_card_name = db.Column(db.String, db.ForeignKey('cards.card_name'), nullable=True)
    deck_image_url = db.Column(db.String, nullable=True)

class UserDeck(db.Model):
    __tablename__ = 'users-decks'
    username = db.Column(db.String, db.ForeignKey('users.username'), primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('decks.deck_id'), primary_key=True)

class DeckCard(db.Model):
    __tablename__ = 'decks-cards'
    deck_id = db.Column(db.Integer, db.ForeignKey('decks.deck_id'), primary_key=True)
    card_name = db.Column(db.String, db.ForeignKey('cards.card_name'), primary_key=True)
    quantity = db.Column(db.Integer)

    __table_args__ = (
        db.Index('ix_deck_card_deck_id', 'deck_id'),
        db.Index('ix_deck_card_card_name', 'card_name'),
    )

class Format(db.Model):
    __tablename__ = 'formats'
    format_name = db.Column(db.String, primary_key=True)

class CardFormat(db.Model):
    __tablename__ = 'cards-formats'
    card_name = db.Column(db.String, db.ForeignKey('cards.card_name'), primary_key=True)
    format_name = db.Column(db.String, db.ForeignKey('formats.format_name'), primary_key=True)
    amount_allowed = db.Column(db.Integer)

'''class Type(db.Model):
    __tablename__ = 'types'
    type_name = db.Column(db.String, primary_key=True)'''

global current_username
global current_deck_id

current_username = None
current_deck_id = None

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/decks')
def decks():
    # Check if user is logged in
    if current_username is None:
        return redirect('/')

    global current_deck_id
    current_deck_id = None  # Reset deck_id for next deck

    sql_query = text("""
        SELECT * 
        FROM decks 
        WHERE deck_id IN (
            SELECT deck_id 
            FROM "users-decks" 
            WHERE username = :username
        )
    """)

    decks = db.session.execute(sql_query, {'username': current_username})

    print(decks)

    print("Current deck id: ", current_deck_id)

    return render_template('decks.html', user_decks=decks)


@app.route('/create_deck', methods=['POST', 'GET'])
def create_deck():
    # Check if user is logged in
    global current_username
    if current_username is None:
        return redirect('/')

    # Get deck ID if resuming an unsaved deck or create a new deck ID
    global current_deck_id

    data = request.get_json()
    if data is not None:
        print(data)
        if data['deck_id'] is not None:
            current_deck_id = data['deck_id']

    if current_deck_id is None:
        max_deck_id = db.session.query(db.func.max(Deck.deck_id)).scalar() or 0
        current_deck_id = max_deck_id + 1

    # Query deck cards for the current deck (if any)
    deck_cards = DeckCard.query.filter_by(deck_id=current_deck_id).all()

    # Query deck cards for the current deck with associated card images
    deck_cards = (
        db.session.query(DeckCard, Card)
        .join(Card, DeckCard.card_name == Card.card_name)  # Assuming DeckCard has a card_id field that links to Card
        .filter(DeckCard.deck_id == current_deck_id)
        .all()
    )

    deck_name = Deck.query.filter_by(deck_id=current_deck_id).first()

    print("current deck: ", current_deck_id)
    print("deck_cards: ", deck_cards)

    if deck_name is not None:
        return render_template('create_deck.html', deck_cards=deck_cards, deck_name = deck_name.deck_name)
    else:
        deck_count = UserDeck.query.filter_by(username=current_username).count()
        return render_template('create_deck.html', deck_cards=deck_cards, deck_name = "deck " + str(deck_count + 1))

@app.route('/delete_deck', methods=['POST'])
def delete_deck():
    # Check if user is logged in
    if current_username is None:
        redirect('/')
    
    # Attempt to find the deck in the database
    data = request.get_json()
    print("DATA: ", data)
    deck_id = data['deck_id']
    print("to delete", deck_id)
    deck_to_delete = Deck.query.filter_by(deck_id=deck_id).first()
    
    try:
        delete_deck_cards = text("DELETE FROM decks-cards WHERE deck_id = :deck_id")
        db.session.execute(delete_deck_cards, {'deck_id': deck_id})
        db.session.commit()
    except Exception as e:
        db.session.rollback()  # Rollback if there was an error

    try:
        delete_user_decks = text("DELETE FROM users-decks WHERE deck_id = :deck_id")
        db.session.execute(delete_user_decks, {'deck_id': deck_id})
        db.session.commit()
    except Exception as e:
        db.session.rollback()  # Rollback if there was an error


    if deck_to_delete:
        try:
            # Delete the deck
            db.session.delete(deck_to_delete)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Deck deleted successfully.'})
        except Exception as e:
            db.session.rollback()  # Rollback in case of an error
            return jsonify({'success': False, 'message': 'An error occurred while deleting the deck.'}), 500
    else:
        return jsonify({'success': False, 'message': 'Deck not found.'}), 404


@app.route('/save_deck', methods=['POST'])
def save_deck():
    # Check if user is logged in
    global current_username
    if current_username is None:
        return redirect('/')

    # Get deck ID if resuming an unsaved deck or create a new deck ID
    global current_deck_id
    if current_deck_id is None:
        return redirect('/decks')

    data = request.get_json()
    deck_name = data.get('deck_name')
    cards = data.get('cards')

    # Check if the deck already exists
    existing_deck = Deck.query.filter_by(deck_id=current_deck_id).first()

    if existing_deck:
        # Update the name of the existing deck
        existing_deck.deck_name = deck_name
    else:
        # Create a new Deck if it doesn't exist
        existing_deck = Deck(deck_id=current_deck_id, deck_name=deck_name)
        db.session.add(existing_deck)

    # Add or update the UserDeck entry (if necessary)
    user_deck = UserDeck.query.filter_by(deck_id=current_deck_id, username=current_username).first()
    if not user_deck:
        user_deck = UserDeck(deck_id=current_deck_id, username=current_username)
        db.session.add(user_deck)

    print("Current username: ", current_username)
    print("Current deck id: ", current_deck_id)

    # Add or update each card in the DeckCard table
    for card in cards:
        card_name = card['card_name']
        quantity = int(card['quantity'])

        # Check if the card already exists in the DeckCard table for this deck
        existing_card = DeckCard.query.filter_by(deck_id=current_deck_id, card_name=card_name).first()
        
        if existing_card:
            # If the card exists, update the quantity
            existing_card.quantity = quantity
        else:
            # If it doesn't exist, add it as a new card
            deck_card = DeckCard(deck_id=current_deck_id, card_name=card_name, quantity=quantity)
            db.session.add(deck_card)

    db.session.commit()

    return jsonify({"message": "Deck saved successfully!"})


@app.route('/search_cards', methods=['POST'])
def search_cards():
    global current_username
    if current_username is None:
        return redirect('/')
    global current_deck_id
    if current_deck_id is None:
        return redirect('/decks')

    data = request.get_json()
    card_name = data.get('card_name', '')
    card_type = data.get('card_type', '')
    card_color = data.get('card_color', '')
    card_ability = data.get('card_ability', '')

    query = Card.query

    if card_name:
        query = query.filter(Card.card_name.ilike(f"%{card_name}%"))
    if card_type:
        query = query.filter(Card.card_type.ilike(f"%{card_type}%"))
    if card_color == 'colorless':
        query = query.filter(~Card.mana_cost.op('regexp')('[WUBRG]'))
    elif card_color:
        query = query.filter(Card.mana_cost.contains(card_color))
    query = query.filter(~Card.card_name.contains('//'))

    query = query.filter(Card.text.ilike(f"%{card_ability}%"))

    cards = query.all()
    print(cards)
    return jsonify([{
        'name': card.card_name,
        'type': card.card_type,
        'mana_cost': card.mana_cost,
        'image_url': card.image_url
    } for card in cards])


@app.route('/add_card', methods=['GET'])
def add_card():
    global current_username
    if current_username is None:
        return redirect('/')
    global current_deck_id
    if current_deck_id is None:
        return redirect('/decks')
    return render_template('add_card.html')

@app.route('/add_card_to_deck', methods=['POST'])
def add_card_to_deck():
    if current_username is None:
        return redirect('/')
    if current_deck_id is None:
        return redirect('/decks')
    data = request.get_json()
    card_name = data.get('card_name')
    sql_query = text("""
    INSERT INTO `decks-cards` (deck_id, card_name, quantity) 
    VALUES (:deck_id, :card_name, 1)
""")
    
    params = {'deck_id': current_deck_id, 'card_name': card_name}
    db.session.execute(sql_query, params)
    db.session.commit()

    # Verify if the card was added
    added_card = DeckCard.query.filter_by(deck_id=current_deck_id, card_name=card_name).first()
    if added_card:
        return jsonify(message='Card added to deck successfully!'), 200
    else:
        return jsonify(message='Failed to add card to deck.'), 400

@app.route('/delete_card', methods=['POST'])
def delete_card():
    if current_username is None:
        return redirect('/')
    if current_deck_id is None:
        return redirect('/decks')
    data = request.get_json()
    card_to_delete = data.get('card_name')
    print("card_to_delete: ", card_to_delete)

    if not card_to_delete:
        return jsonify({'success': False, 'error': 'Card ID is required'}), 400

    # Find and delete the card from the deck
    deck_card = DeckCard.query.filter_by(deck_id=current_deck_id, card_name=card_to_delete).first()
    if not deck_card:
        return jsonify({'success': False, 'error': 'Card not found'}), 404

    db.session.delete(deck_card)
    db.session.commit()

    return jsonify({'success': True})



@app.route('/generate-report', methods=['GET', 'POST'])
def generate_report():
    if current_username is None:
        return redirect('/')

    # Ensure current_deck_id is available globally
    if current_deck_id is None:
        return redirect('/decks')

    # Get the selected card color from the request (default is 'All')
    card_color = request.args.get('color', "")
    print("color", card_color)

    # Start building the query
    query = db.session.query(Card.card_name, Card.mana_cost, db.func.sum(DeckCard.quantity).label('count')) \
        .join(DeckCard, DeckCard.card_name == Card.card_name) \
        .filter(DeckCard.deck_id == current_deck_id)


    # Add color filter if specified
    if card_color == 'colorless':
        query = query.filter(~Card.mana_cost.op('regexp')('[WUBRG]'))  # Exclude cards containing any color
    elif card_color:
        query = query.filter(Card.mana_cost.like(f"%{card_color}%"))

    # Group by card name and mana cost
    query = query.group_by(Card.card_name, Card.mana_cost)

    # Execute the query and fetch results
    cards = query.all()

    print("cards", cards)

    # Calculate the report data
    unique_cards = len(set(card.card_name for card in cards))  # Count distinct card names
    total_cards = sum(card.count for card in cards)  # Count total cards
    mana_distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, "7+": 0}

    for card in cards:
        mana_value = 0  # Default value for non-numeric mana cost
        
        # Check if the mana cost contains a numeric part and add it to mana_value
        numeric_mana_cost = ''.join(filter(str.isdigit, card.mana_cost))
        if numeric_mana_cost:
            mana_value += int(numeric_mana_cost)  # Convert numeric part to integer and add to mana_value
        
        # Count the number of color symbols (W, U, B, R, G)
        color_symbols = ['W', 'U', 'B', 'R', 'G']
        for symbol in color_symbols:
            mana_value += card.mana_cost.count(f'{{{symbol}}}')  # Add 1 for each color symbol in the mana cost
        
        # Distribute the mana count
        if mana_value >= 7:
            mana_distribution["7+"] += card.count
        elif mana_value in mana_distribution:
            mana_distribution[mana_value] += card.count

    # Return the rendered template with the data
    return render_template('generate_report.html', card_color=card_color,
                           unique_cards=unique_cards,
                           total_cards=total_cards,
                           mana_distribution=mana_distribution)


# Routes for Login and Signup
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    print("Received signup data:", data)  # Print the received data
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Username already exists"}), 409

    new_user = User(username=data['username'], password=data['password'])
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "Account created successfully"}), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()  # Get the JSON data sent from the front end
    print("Received login data:", data)  # Print the received data
    username = data.get('username')
    password = data.get('password')
    
    # Check if the user exists in the database
    user = User.query.filter_by(username=username, password=password).first()
    
    testuser = User.query.filter_by(username=username).first()
    print(testuser)

    if user:
        print("User found:", username)  # Print username if found
        global current_username
        current_username = username
        return jsonify({'message': 'Login successful'}), 200
    else:
        print("Invalid credentials for:", username)  # Print when credentials are invalid
        return jsonify({'message': 'Invalid credentials'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({"message": "Logged out"}), 200

if __name__ == '__main__':
    app.run(debug=True)