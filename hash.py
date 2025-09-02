import bcrypt
password = 'client123'  # Change this to your desired password
hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
print(hashed.decode('utf-8'))