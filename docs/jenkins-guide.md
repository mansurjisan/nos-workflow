# Jenkins CI/CD Guide for NOS Workflow

This guide covers setting up and using Jenkins for building and testing the NOS Workflow Singularity container.

## Prerequisites

- Java 17 or later
- Apptainer/Singularity installed
- Test data at `/mnt/f/STOFS_CI_DATA` (or update `Jenkinsfile` paths)

## Installing Jenkins

### Option 1: WAR File (Recommended for local testing)

```bash
# Create Jenkins directory
mkdir -p ~/jenkins && cd ~/jenkins

# Download Jenkins WAR
wget https://get.jenkins.io/war-stable/latest/jenkins.war

# Run Jenkins
java -jar jenkins.war
```

Jenkins will start on http://localhost:8080

### Option 2: System Package (Debian/Ubuntu)

```bash
# Install Java
sudo apt-get update
sudo apt-get install -y fontconfig openjdk-17-jre

# Add Jenkins repo
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key | sudo tee /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" | sudo tee /etc/apt/sources.list.d/jenkins.list > /dev/null

# Install Jenkins
sudo apt-get update
sudo apt-get install -y jenkins

# Start Jenkins
sudo systemctl enable jenkins
sudo systemctl start jenkins
```

## Initial Setup

1. Open http://localhost:8080 in your browser
2. Get the initial admin password:
   ```bash
   # WAR file method
   cat ~/.jenkins/secrets/initialAdminPassword

   # System package method
   sudo cat /var/lib/jenkins/secrets/initialAdminPassword
   ```
3. Paste the password and click **Continue**
4. Select **Install suggested plugins**
5. Create your admin user
6. Complete the setup wizard

## Creating the Pipeline Job

1. Click **New Item** on the dashboard
2. Enter name: `nos-workflow`
3. Select **Pipeline**
4. Click **OK**

### Configure the Pipeline

1. Scroll to **Pipeline** section
2. Set **Definition** to: `Pipeline script from SCM`
3. Set **SCM** to: `Git`
4. **Repository URL**: `https://github.com/mansurjisan/nos-workflow.git`
5. **Branch Specifier**: `*/main`
6. **Script Path**: `Jenkinsfile`
7. Click **Save**

## Running Builds

### Manual Build

1. Go to the **nos-workflow** job
2. Click **Build Now** in the left sidebar
3. Watch progress in **Build History**

### View Build Progress

1. Click on the build number (e.g., `#1`) in Build History
2. Click **Console Output** for live logs
3. Or check **Build Executor Status** on the dashboard for running builds

### Build Status Icons

| Icon | Meaning |
|------|---------|
| Blue (blinking) | Currently building |
| Blue (solid) | Success |
| Red | Failed |
| Grey | Not built / Aborted |

## Pipeline Stages

The Jenkinsfile defines these stages:

| Stage | Description | Condition |
|-------|-------------|-----------|
| Checkout | Clone repository | Always |
| Validate Definition | Check .def file exists | Always |
| Build Container | Run `apptainer build` | Always |
| Test Container | Test ADCIRC, ecFlow, wgrib2, Python | Always |
| Setup Test Data | Prepare sandbox directories | If test data exists |
| Run Prep-Forecast Test | Execute STOFS workflow | If test data exists |
| Verify Outputs | Check output files | If test data exists |
| Archive Container | Save .sif as artifact | Main branch only |

## Triggering Builds from GitHub

### Option 1: GitHub Webhooks (Requires Public URL)

If Jenkins is accessible from the internet:

1. **Install GitHub Plugin in Jenkins:**
   - Manage Jenkins → Plugins → Available plugins
   - Search "GitHub Integration" → Install
   - Restart Jenkins

2. **Configure Job:**
   - Job → Configure → Build Triggers
   - Check "GitHub hook trigger for GITScm polling"
   - Save

3. **Add Webhook in GitHub:**
   - Go to: https://github.com/YOUR_USER/nos-workflow/settings/hooks
   - Click "Add webhook"
   - Payload URL: `http://YOUR_JENKINS_URL:8080/github-webhook/`
   - Content type: `application/json`
   - Events: "Just the push event"
   - Save

### Option 2: ngrok Tunnel (For Local Jenkins)

If Jenkins runs on localhost, use ngrok to create a public URL:

```bash
# Install ngrok
# Download from https://ngrok.com/download

# Start tunnel
ngrok http 8080
```

Use the ngrok URL (e.g., `https://abc123.ngrok.io`) as your webhook Payload URL.

### Option 3: Polling (No Webhook Required)

Configure Jenkins to periodically check for changes:

1. Job → Configure → Build Triggers
2. Check "Poll SCM"
3. Schedule: `H/5 * * * *` (every 5 minutes)
4. Save

### Option 4: GitHub Actions + Jenkins API

Trigger Jenkins from GitHub Actions:

```yaml
# .github/workflows/trigger-jenkins.yml
name: Trigger Jenkins

on:
  push:
    branches: [main]

jobs:
  trigger:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Jenkins Build
        run: |
          curl -X POST "http://YOUR_JENKINS_URL:8080/job/nos-workflow/build" \
            --user "${{ secrets.JENKINS_USER }}:${{ secrets.JENKINS_TOKEN }}"
```

## Data Paths

The Jenkinsfile expects test data at these locations:

```groovy
DATA_ROOT = '/mnt/f/STOFS_CI_DATA'
SANDBOX_ROOT = '/mnt/f/STOFS_CI_DATA/stofs_sandbox'
```

Required data structure:
```
/mnt/f/STOFS_CI_DATA/
├── extracted_gfs/
├── extracted_hrrr/
├── extracted_nwm/
├── extracted_rtofs/
├── 20250503/          # DCOM data
└── stofs_sandbox/     # Output directory (created automatically)
```

Update these paths in `Jenkinsfile` if your data is in a different location.

## Troubleshooting

### Jenkins won't start
```bash
# Check if port 8080 is in use
lsof -i :8080

# Run on different port
java -jar jenkins.war --httpPort=9090
```

### Build fails at "Build Container"
- Check disk space: `df -h`
- Check memory: `free -h`
- View full logs in Console Output

### Test stages are skipped
- Verify `DATA_ROOT` path exists
- Check file permissions
- Update paths in Jenkinsfile if needed

### Permission denied errors
```bash
# Add Jenkins user to docker/apptainer group
sudo usermod -aG docker jenkins
sudo usermod -aG apptainer jenkins
```

## Stopping Jenkins

### WAR file method
Press `Ctrl+C` in the terminal running Jenkins

### System service method
```bash
sudo systemctl stop jenkins
```

## Useful Links

- Jenkins Documentation: https://www.jenkins.io/doc/
- Pipeline Syntax: https://www.jenkins.io/doc/book/pipeline/syntax/
- GitHub Plugin: https://plugins.jenkins.io/github/
