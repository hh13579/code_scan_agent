pipeline {
  agent any

  options {
    timestamps()
    ansiColor('xterm')
  }

  parameters {
    string(name: 'REPO_PATH', defaultValue: '/Users/didi/work/sdk-env/navi-engine-v2', description: '待扫描仓库的绝对路径')
    string(name: 'BRANCH1', defaultValue: 'origin/main', description: '基线分支 / branch1')
    string(name: 'BRANCH2', defaultValue: 'HEAD', description: '目标分支 / branch2')
    choice(name: 'FAIL_ON', choices: ['critical', 'high', 'medium', 'low', 'info'], description: '命中该级别及以上 finding 时返回失败')
    string(name: 'OUTPUT_DIR', defaultValue: 'artifacts', description: '产物输出目录（相对当前 workspace）')
    booleanParam(name: 'NO_LLM_TRIAGE', defaultValue: true, description: '扫描阶段禁用 LLM triage')
    booleanParam(name: 'ENABLE_CN_REPORT', defaultValue: true, description: '扫描完成后自动生成中文报告')
    booleanParam(name: 'CN_REPORT_LOCAL_FALLBACK', defaultValue: true, description: 'DeepSeek 不可用时允许退化为本地中文报告')
  }

  stages {
    stage('Scan') {
      steps {
        script {
          String artifactDir = "${env.WORKSPACE}/${params.OUTPUT_DIR}"
          sh "mkdir -p '${artifactDir}'"

          List<String> cmd = [
            'python3',
            'main.py',
            params.REPO_PATH,
            '--branch1', params.BRANCH1,
            '--branch2', params.BRANCH2,
            '--out', "${artifactDir}/report.json",
            '--out-zh', "${artifactDir}/report_zh.md",
            '--out-sarif', "${artifactDir}/report.sarif",
            '--log-out', "${artifactDir}/run.log",
            '--fail-on', params.FAIL_ON,
          ]

          if (params.NO_LLM_TRIAGE) {
            cmd += ['--no-llm']
          }

          if (params.ENABLE_CN_REPORT) {
            cmd += [
              '--cn-report-out', "${artifactDir}/report_cn.md",
              '--cn-report-json-out', "${artifactDir}/report_cn.json",
            ]
            if (params.CN_REPORT_LOCAL_FALLBACK) {
              cmd += ['--cn-report-local-fallback']
            }
          }

          String quoted = cmd.collect { "'${it.replace("'", "'\"'\"'")}'" }.join(' ')
          int scanStatus = sh(script: quoted, returnStatus: true)
          writeFile(file: "${artifactDir}/scan_exit_code.txt", text: "${scanStatus}\n")

          if (scanStatus == 2) {
            currentBuild.description = "fail-on threshold hit (${params.FAIL_ON})"
            error("code_scan_agent fail-on threshold hit (${params.FAIL_ON})")
          }

          if (scanStatus != 0) {
            currentBuild.description = "scan failed (${scanStatus})"
            error("code_scan_agent exited with status ${scanStatus}")
          }
        }
      }
    }
  }

  post {
    always {
      archiveArtifacts artifacts: "${params.OUTPUT_DIR}/**", allowEmptyArchive: true
    }
  }
}
