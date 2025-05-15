# How to set up stocky

### Step 1: Set up the project

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com) and create a project.
2. In **Quick Access**, click **APIs & Services**.
3. At the top, press **Enable APIs and services**.
4. Add the following APIs:

   * `Google Sheets API`
   * `Google Drive API`

---

### Step 2: Create a service account

1. Return to [https://console.cloud.google.com](https://console.cloud.google.com).
2. Under **Quick Access**, press **IAM & Admin**.
3. In the sidebar, click **Service Accounts**.
4. Near the top, click **Create Service Account**.
5. Enter a name (e.g., `stocky`) and press **Create and Continue**.
6. Under **Select a role**, choose:

   * **Basic** > **Editor**
7. Press **Done**.

---

### Step 3: Generate a key

1. Click the account you just created.
2. Go to the **Keys** tab.
3. Click **Add Key** > **Create New Key**.
4. Select **JSON**, then press **Create**.
5. Download the JSON file.

---

### Step 4: Convert credentials

1. Open [https://www.base64encode.org/](https://www.base64encode.org/)
2. Paste the entire contents of the `.json` file and copy the output.

---

### Step 5: Set environment variables

You'll need to define the following three variables:

* `GOOGLE_CREDS` — the base64-encoded JSON from above
* `GOOGLE_SHEET_URL` — link to your spreadsheet
* `GOOGLE_FOLDER_URL` — link to your Drive folder

---

### Step 6: Share access

1. Create a **spreadsheet** and a **folder** in Google Drive.
2. Share **both** with the service account email (looks like `stocky@exampleproject.iam.gserviceaccount.com`) and give it **Editor** access.

---

### Step 7: Load spreadsheet template

1. Download `spreadsheet_template.xlsx`.
2. Go to your spreadsheet in Google Drive.
3. Click **File > Import**.
4. Go to the **Upload** tab, select the file.
5. Change **Import location** to **Replace spreadsheet** and press **Import data**.