import os
import logging
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from flask_mysqldb import MySQL
import paho.mqtt.client as mqtt
import json
import requests

seq48 = ""

# Configuração de logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config['SESSION_PERMANENT'] = False  # Sessão não persiste após fechar o navegador
app.secret_key = 'your_secret_key'
bcrypt = Bcrypt(app)

# Configurações do banco de dados MySQL
app.config['MYSQL_HOST'] = 'sql10.freemysqlhosting.net'
app.config['MYSQL_USER'] = 'sql10746168'
app.config['MYSQL_PASSWORD'] = 'Py2RUvw6my'
app.config['MYSQL_DB'] = 'sql10746168'

mysql = MySQL(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Tópicos MQTT
TOPIC_STATUS = "home/esp32/status"
TOPIC_COMMAND = "home/esp32/leds"

# Estado inicial dos LEDs
led_status = {"led1": False, "led2": False, "led3": False, "led4": False}

# Classe do usuário
class User(UserMixin):
    def __init__(self, id, email, broker, username, password, port):
        self.id = id
        self.email = email
        self.broker = broker
        self.username = username
        self.password = password
        self.port = port
        
@login_manager.user_loader
def load_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    if user:
        logging.info(f"Usuário carregado: {user[1]}")
        return User(user[0], user[1], user[3], user[4], user[5], user[6])
    logging.warning(f"Usuário com ID {user_id} não encontrado.")
    return None

# Configuração MQTT
mqtt_client = mqtt.Client()
mqtt_client._initialized = False

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info("Conectado ao broker MQTT com sucesso!")
        client.subscribe(TOPIC_STATUS)
        logging.debug(f"Inscrito no tópico: {TOPIC_STATUS}")
    else:
        logging.error(f"Falha ao conectar ao broker MQTT: Código {rc}")

def on_message(client, userdata, msg):
    global led_status
    try:
        payload = json.loads(msg.payload.decode())
        for led, state in payload.items():
            if led in led_status:
                led_status[led] = state
        logging.info(f"Estado dos LEDs atualizado: {led_status}")
    except Exception as e:
        logging.error(f"Erro ao processar mensagem MQTT: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def configurar_mqtt():
    global mqtt_client
    if not mqtt_client._initialized:
        try:
            mqtt_client.tls_set()  # Configura conexão segura
            mqtt_client.tls_insecure_set(True)  # Ignora a validação de certificado
            mqtt_client.username_pw_set(current_user.username, current_user.password)
            mqtt_client.connect(current_user.broker, int(current_user.port))
            mqtt_client.loop_start()
            mqtt_client._initialized = True
            logging.info("Cliente MQTT configurado com sucesso!")
        except Exception as e:
            logging.error(f"Erro ao configurar o cliente MQTT: {e}")
            raise

@app.route('/')
def inicio():
    return render_template('index.html')

@app.route('/tutorial')
def tutorial():
    return render_template('tutorial.html')

@app.route('/<pagina>')
def erro404(pagina):
    return render_template('erro404.html', pagina=pagina)

@app.route('/recuperar_senha', methods=['GET'])
def recuperar_senha():
    return render_template('recuperar_senha.html')

@app.route('/procurar_email', methods=['POST'])
def procurar_email():
    email = request.form.get('email')  # Obtém o e-mail enviado via POST
    
    if not email:
        return jsonify({"erro": "O e-mail não foi fornecido"}), 400

    import re
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"erro": "E-mail inválido"}), 400

    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
        resultado = cursor.fetchone()

        if resultado:
            from apimsg import enviar_cod
            from gerados import gerar_sequencia

            seq = gerar_sequencia()

            # Salvar o código no banco, associado ao e-mail
            cursor.execute("""
                UPDATE users 
                SET verification_code = %s 
                WHERE LOWER(email) = LOWER(%s)
            """, (seq, email))
            mysql.connection.commit()

            mensagem = f"O seu código de verificação é: {seq}."
            enviar_cod(email, mensagem)

            cursor.close()
            return jsonify({"encontrado": True, "mensagem": "Código de verificação enviado com sucesso!"}), 200
        else:
            cursor.close()
            return jsonify({"encontrado": False, "mensagem": "E-mail não encontrado"}), 404

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route('/validar_codigo', methods=['POST'])
def validar_codigo():
    email = request.form.get('email')
    codigo = request.form.get('codigo')

    if not email or not codigo:
        return jsonify({"erro": "E-mail ou código não fornecido"}), 400

    try:
        cursor = mysql.connection.cursor()
        cursor.execute("""
            SELECT * FROM users 
            WHERE LOWER(email) = LOWER(%s) AND verification_code = %s
        """, (email, codigo))
        resultado = cursor.fetchone()

        if resultado:
            from apimsg import enviar_cod
            from gerados import gerar_sequencia48

            seq48 = gerar_sequencia48()

            # Salvar seq48 no banco, associado ao e-mail
            cursor.execute("""
                UPDATE users 
                SET reset_code = %s, verification_code = NULL
                WHERE LOWER(email) = LOWER(%s)
            """, (seq48, email))
            mysql.connection.commit()

            mensagem = f"Para redefinir sua senha, acesse o link: http://192.168.18.79:5000/alterar_senha/{seq48}"
            enviar_cod(email, mensagem)

            cursor.close()
            return jsonify({"validado": True, "mensagem": "Link de redefinição enviado com sucesso!"}), 200
        else:
            cursor.close()
            return jsonify({"validado": False, "mensagem": "Código inválido ou e-mail não encontrado"}), 404

    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/alterar_senha/<seq48>', methods=['GET', 'POST'])
def alterar_senha(seq48):
    if request.method == 'GET':
        # Renderiza uma página HTML para redefinir a senha
        return render_template('alterar_senha.html', seq48=seq48)

    elif request.method == 'POST':
        # Lógica para alterar a senha (como já implementado)
        try:
            dados = request.get_json()
            email = dados.get('email')
            nova_senha = dados.get('nova_senha')

            if not email or not nova_senha:
                return jsonify({"erro": "E-mail e nova senha são obrigatórios"}), 400

            # Verifica se o seq48 é válido e pertence ao e-mail fornecido
            cursor = mysql.connection.cursor()
            cursor.execute("""
                SELECT * FROM users 
                WHERE LOWER(email) = LOWER(%s) AND reset_code = %s
            """, (email, seq48))
            resultado = cursor.fetchone()

            if not resultado:
                return jsonify({"erro": "Código de redefinição inválido ou expirado"}), 400

            nova_senha_hash = bcrypt.generate_password_hash(nova_senha).decode('utf-8')

            # Atualiza a senha no banco
            cursor.execute("""
                UPDATE users 
                SET password_hash = %s, reset_code = NULL
                WHERE LOWER(email) = LOWER(%s)
            """, (nova_senha_hash, email))
            mysql.connection.commit()

            if cursor.rowcount > 0:
                return jsonify({"mensagem": "Senha alterada com sucesso"}), 200
            else:
                return jsonify({"erro": "E-mail não encontrado"}), 404

        except Exception as e:
            return jsonify({"erro": f"Erro interno: {str(e)}"}), 500


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        broker = request.form['broker']
        mqtt_user = request.form['mqtt_user']
        mqtt_password = request.form['mqtt_password']
        mqtt_port = int(request.form['mqtt_port'])

        # API de validação de e-mail
        API_KEY = '9e22da46e85c4bab9684168eb8acd81e'
        API_URL = f"https://emailvalidation.abstractapi.com/v1/?api_key={API_KEY}&email={email}"

        # Fazendo a requisição para a API
        response = requests.get(API_URL)
        if response.status_code == 200:  # Se a API respondeu com sucesso
            data = response.json()  # Decodifica a resposta JSON
            if not data.get('deliverability') == "DELIVERABLE":  # Verifica se o e-mail é válido
                flash("O e-mail fornecido não é válido ou não pode ser entregue.", "danger")
                return redirect(url_for('register'))
        else:
            flash("Erro ao validar o e-mail. Tente novamente mais tarde.", "danger")
            return redirect(url_for('register'))

        # Verificação do broker MQTT
        def verify_broker():
            client = mqtt.Client()
            mqtt_client._initialized = False
            client.username_pw_set(mqtt_user, mqtt_password)
            try:
                client.connect(broker, mqtt_port, 10)
                client.disconnect()
                return True
            except Exception as e:
                logging.error(f"Erro ao conectar ao broker MQTT: {e}")
                return False

        if not verify_broker():
            flash("Verfique as credenciais do broker, não foi possível se conectar!.", "danger")
            return redirect(url_for('register'))

        # Hash da senha
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Inserção no banco de dados
        cur = mysql.connection.cursor()
        try:
            cur.execute("""
                INSERT INTO users (email, password_hash, mqtt_broker, mqtt_username, mqtt_password, mqtt_port)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (email, hashed_password, broker, mqtt_user, mqtt_password, mqtt_port))
            mysql.connection.commit()
            logging.info(f"Novo usuário registrado: {email}")
            
            # Função para confirmar cadastro no e-mail
            mensagem = (
                "Você se registrou, e já está pronto para testar a Dashboard de Leds! "
                "Para qualquer dúvida, acesse o /tutorial. Valeu!"
            )
            from apimsg import enviar_email
            enviar_email(email, mensagem)
            
            flash("Registrado com sucesso! Verifique seu e-mail para mais informações.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            logging.error(f"Erro ao registrar usuário {email}: {e}")
            flash(f"Erro ao registrar: {e}", "danger")
        finally:
            cur.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()

        if user and bcrypt.check_password_hash(user[2], password):
            user_obj = User(user[0], user[1], user[3], user[4], user[5], user[6])
            login_user(user_obj)
            logging.info(f"Usuário autenticado: {email}")
            flash("Login realizado com sucesso!")
            return redirect(url_for('dashboard'))
        else:
            logging.warning(f"Tentativa de login falhou para o email: {email}")
            flash("Credenciais inválidas!", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logging.info(f"Usuário desconectado: {current_user.email}")
    logout_user()
    flash("Você saiu da conta.", "info")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        configurar_mqtt()
    except Exception:
        flash("Erro ao conectar ao broker MQTT. Verifique as configurações.", "danger")
        return redirect(url_for('inicio'))
    return render_template('dashboard.html', broker=current_user.broker)

@app.route('/update_led', methods=['POST'])
@login_required
def update_led():
    global led_status
    data = request.get_json()
    for led, state in data.items():
        if led in led_status:
            led_status[led] = bool(state)
            logging.info(f"{led} {'ligado' if state else 'desligado'} pelo usuário {current_user.email}")
    mqtt_payload = json.dumps(led_status)
    mqtt_client.publish(TOPIC_COMMAND, mqtt_payload)
    logging.debug(f"Mensagem publicada no tópico {TOPIC_COMMAND}: {mqtt_payload}")
    return jsonify({"status": "OK", "led_status": led_status}), 200

@app.route('/led_status', methods=['GET'])
@login_required
def get_led_status():
    logging.info(f"Status dos LEDs solicitado por {current_user.email}: {led_status}")
    return jsonify(led_status)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logging.info("Iniciando o servidor Flask...")
    app.run(host='0.0.0.0', port=port)