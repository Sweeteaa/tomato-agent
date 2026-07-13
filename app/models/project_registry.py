from typing import List, Optional

from pydantic import BaseModel, Field


class ProjectRegistryItem(BaseModel):
    name: str = Field(..., description="项目唯一名称")
    root_path: str = Field(..., description="项目绝对路径")
    enabled: bool = Field(default=True, description="是否启用该项目")
    framework: str = Field(default="unknown", description="前端框架")
    build_tool: str = Field(default="unknown", description="构建工具")
    package_manager: str = Field(default="unknown", description="包管理器")
    dev_command: str = Field(default="", description="推荐启动命令")
    src_dir: str = Field(default="src", description="源码目录")
    router_file_candidates: List[str] = Field(default_factory=list, description="候选路由文件")
    api_dir_candidates: List[str] = Field(default_factory=list, description="候选 API 目录")
    store_type: str = Field(default="unknown", description="状态管理方案")
    component_dirs: List[str] = Field(default_factory=list, description="公共组件目录")
    page_dirs: List[str] = Field(default_factory=list, description="页面目录")
    module_summary: str = Field(default="", description="模块说明")
    last_scan_at: Optional[str] = Field(default=None, description="最近扫描时间")
    scan_status: str = Field(default="pending", description="扫描状态")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


class ProjectRegistryCreate(BaseModel):
    name: str
    root_path: str
    enabled: bool = True
    framework: str = "unknown"
    build_tool: str = "unknown"
    package_manager: str = "unknown"
    dev_command: str = ""
    src_dir: str = "src"
    router_file_candidates: List[str] = Field(default_factory=list)
    api_dir_candidates: List[str] = Field(default_factory=list)
    store_type: str = "unknown"
    component_dirs: List[str] = Field(default_factory=list)
    page_dirs: List[str] = Field(default_factory=list)
    module_summary: str = ""
    last_scan_at: Optional[str] = None
    scan_status: str = "pending"


class ProjectRegistryUpdate(BaseModel):
    root_path: Optional[str] = None
    enabled: Optional[bool] = None
    framework: Optional[str] = None
    build_tool: Optional[str] = None
    package_manager: Optional[str] = None
    dev_command: Optional[str] = None
    src_dir: Optional[str] = None
    router_file_candidates: Optional[List[str]] = None
    api_dir_candidates: Optional[List[str]] = None
    store_type: Optional[str] = None
    component_dirs: Optional[List[str]] = None
    page_dirs: Optional[List[str]] = None
    module_summary: Optional[str] = None
    last_scan_at: Optional[str] = None
    scan_status: Optional[str] = None


class ProjectRegistryImportRequest(BaseModel):
    root_path: Optional[str] = None
    overwrite_existing: bool = False


class ProjectRegistryImportResult(BaseModel):
    imported: int
    skipped: int
    projects: List[ProjectRegistryItem]
